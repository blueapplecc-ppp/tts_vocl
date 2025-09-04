from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from flask_login import login_user, logout_user, current_user, login_required
from .auth import (
    handle_google_login, 
    handle_google_callback, 
    handle_logout, 
    handle_access_denied,
    TtsUserMixin
)

# 创建鉴权 Blueprint
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login')
def login():
    """登录页面"""
    return handle_google_login()

@auth_bp.route('/callback')
def callback():
    """OAuth 回调"""
    return handle_google_callback()

@auth_bp.route('/logout')
def logout():
    """登出"""
    return handle_logout()

@auth_bp.route('/access-denied')
def access_denied():
    """访问拒绝页面"""
    return handle_access_denied()
