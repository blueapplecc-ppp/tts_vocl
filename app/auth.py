import os
import secrets
import requests
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode
from flask import render_template, redirect, url_for, request, session, flash, current_app, jsonify
from flask_login import login_user, logout_user, current_user, login_required, UserMixin
from requests_oauthlib import OAuth2Session
from .models import get_session, TtsUser


class TtsUserMixin(UserMixin):
    """User mixin for Flask-Login compatibility"""
    def __init__(self, user_id, email, name, avatar_url, platform, platform_user_id, is_whitelisted=False, is_admin=False):
        self.id = user_id
        self.email = email
        self.name = name
        self.avatar_url = avatar_url
        self.platform = platform
        self.platform_user_id = platform_user_id
        self.is_whitelisted = is_whitelisted
        self.is_admin = is_admin
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False

    def get_id(self):
        return str(self.id)


def ensure_dev_user() -> int:
    """确保开发用户存在并返回用户ID"""
    with get_session() as s:
        user = s.query(TtsUser).filter(TtsUser.platform == 'dev', TtsUser.platform_user_id == 'dev').first()
        if user:
            return user.id
        user = TtsUser(
            unified_user_id='dev',
            name='Developer',
            email='dev@local',
            avatar_url=None,
            platform='dev',
            platform_user_id='dev',
            is_whitelisted=True,
            is_admin=True
        )
        s.add(user)
        s.commit()
        return user.id


def get_current_user_id(auth_enabled: bool, request) -> int:
    """获取当前用户ID（兼容现有逻辑）"""
    if not auth_enabled:
        # 开发模式：固定开发者用户
        return ensure_dev_user()
    
    # 鉴权模式：从 Flask-Login 获取用户
    if hasattr(request, 'user') and request.user and request.user.is_authenticated:
        return request.user.id
    
    # 回退到开发用户
    return ensure_dev_user()


def get_google_oauth_session(state=None, token=None):
    """创建 Google OAuth 会话"""
    # 允许 HTTP 在开发环境中
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    # 禁用严格范围检查以处理 Google 的范围变化
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
    
    # 从配置中获取 OAuth 设置
    config = current_app.config if hasattr(current_app, 'config') else {}
    oauth_config = config.get('OAUTH', {}).get('GOOGLE', {})
    
    return OAuth2Session(
        oauth_config.get('CLIENT_ID'),
        scope=['openid', 'email', 'profile'],
        redirect_uri=oauth_config.get('REDIRECT_URI'),
        state=state,
        token=token
    )


def handle_google_login():
    """处理 Google 登录"""
    if current_user.is_authenticated:
        if current_user.is_whitelisted:
            return redirect(url_for('main.text_library'))
        else:
            return redirect(url_for('auth.access_denied'))
    
    # 检查是否有 Google OAuth 配置
    config = current_app.config if hasattr(current_app, 'config') else {}
    oauth_config = config.get('OAUTH', {}).get('GOOGLE', {})
    
    if not oauth_config.get('CLIENT_ID') or not oauth_config.get('CLIENT_SECRET'):
        flash('Google OAuth 配置未设置，请联系管理员', 'error')
        return render_template('auth/login.html', oauth_available=False)
    
    # 生成 OAuth 安全状态
    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state
    
    # 创建 OAuth 会话并获取授权 URL
    google = get_google_oauth_session(state=state)
    authorization_url, _ = google.authorization_url(
        'https://accounts.google.com/o/oauth2/auth',
        access_type='offline',
        prompt='select_account',
        include_granted_scopes='true'
    )
    
    return redirect(authorization_url)


def handle_google_callback():
    """处理 Google OAuth 回调"""
    # 验证状态参数
    if request.args.get('state') != session.get('oauth_state'):
        flash('认证状态验证失败，请重试', 'error')
        return redirect(url_for('auth.login'))
    
    # 检查回调中的错误
    if request.args.get('error'):
        flash(f'Google 认证失败: {request.args.get("error")}', 'error')
        return redirect(url_for('auth.login'))
    
    try:
        # 获取授权码并交换令牌
        google = get_google_oauth_session(state=session.get('oauth_state'))
        config = current_app.config if hasattr(current_app, 'config') else {}
        oauth_config = config.get('OAUTH', {}).get('GOOGLE', {})
        
        token = google.fetch_token(
            'https://oauth2.googleapis.com/token',
            authorization_response=request.url,
            client_secret=oauth_config.get('CLIENT_SECRET')
        )
        
        # 从 Google 获取用户信息
        google = get_google_oauth_session(token=token)
        user_info = google.get('https://www.googleapis.com/oauth2/v2/userinfo').json()
        
        # 检查用户是否存在或创建新用户
        with get_session() as s:
            user = s.query(TtsUser).filter(
                TtsUser.platform == 'google',
                TtsUser.platform_user_id == user_info['id']
            ).first()
            
            if not user:
                # 创建新用户
                user = TtsUser(
                    unified_user_id=f"google_{user_info['id']}",
                    name=user_info['name'],
                    email=user_info['email'],
                    avatar_url=user_info.get('picture'),
                    platform='google',
                    platform_user_id=user_info['id'],
                    is_whitelisted=False,
                    is_admin=False
                )
                
                # 检查是否是超级管理员
                super_admins = config.get('SUPER_ADMIN_EMAILS', [])
                if user_info['email'] in super_admins:
                    user.is_whitelisted = True
                    user.is_admin = True
                
                s.add(user)
            else:
                # 更新现有用户信息
                user.name = user_info['name']
                user.avatar_url = user_info.get('picture')
                
                # 更新管理员状态（如果需要）
                super_admins = config.get('SUPER_ADMIN_EMAILS', [])
                if user_info['email'] in super_admins:
                    user.is_admin = True
                    user.is_whitelisted = True
            
            # 更新最后登录时间
            user.last_login = datetime.utcnow()
            s.commit()
            
            # 创建 Flask-Login 用户对象
            flask_user = TtsUserMixin(
                user_id=user.id,
                email=user.email,
                name=user.name,
                avatar_url=user.avatar_url,
                platform=user.platform,
                platform_user_id=user.platform_user_id,
                is_whitelisted=user.is_whitelisted,
                is_admin=user.is_admin
            )
            
            # 登录用户
            login_user(flask_user, remember=True)
            
            # 清除 OAuth 状态
            session.pop('oauth_state', None)
            
            # 检查白名单状态
            if not user.is_whitelisted:
                return redirect(url_for('auth.access_denied'))
            
            # 重定向到目标页面或首页
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            return redirect(url_for('main.text_library'))
            
    except Exception as e:
        current_app.logger.error(f'OAuth callback error: {str(e)}')
        flash('认证过程中发生错误，请重试', 'error')
        return redirect(url_for('auth.login'))


def handle_logout():
    """处理用户登出"""
    logout_user()
    flash('您已成功登出', 'success')
    return redirect(url_for('auth.login'))


def handle_access_denied():
    """处理访问拒绝页面"""
    return render_template('auth/access_denied.html'), 403


def auth_required(f):
    """装饰器：需要认证"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(current_user, "is_authenticated") or not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_whitelisted:
            return redirect(url_for('auth.access_denied'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """装饰器：需要管理员权限"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(current_user, "is_authenticated") or not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_whitelisted:
            return redirect(url_for('auth.access_denied'))
        if not current_user.is_admin:
            flash('你没有权限访问此页面', 'error')
            return redirect(url_for('main.text_library'))
        return f(*args, **kwargs)
    return decorated_function


def whitelisted_required(f):
    """装饰器：需要白名单权限（用于 API 端点）"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(current_user, "is_authenticated") or not current_user.is_authenticated:
            return {'error': 'Authentication required'}, 401
        if not current_user.is_whitelisted:
            return {'error': 'Access denied'}, 403
        return f(*args, **kwargs)
    return decorated_function
