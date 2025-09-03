from flask import Blueprint, render_template, request, redirect, url_for, current_app, jsonify, Response
import logging
import asyncio
from sqlalchemy import select, desc, asc
from .models import get_session, TtsText, TtsAudio
from .tasks import executor, run_tts_and_upload
from .auth import get_current_user_id
import os
import io
import json
import time

bp = Blueprint('main', __name__)
logger = logging.getLogger(__name__)


@bp.get('/')
def index():
    q = request.args.get('q', '').strip()
    order = request.args.get('order', 'desc')
    page = int(request.args.get('page', 1))
    selected_id = request.args.get('selected_id')
    page_size = 40

    with get_session() as s:
        stmt = select(TtsText).where(TtsText.is_deleted == 0)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(TtsText.title.like(like))
        stmt = stmt.order_by(desc(TtsText.created_at) if order == 'desc' else asc(TtsText.created_at))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        items = s.execute(stmt).scalars().all()

        audios_map = {}
        text_ids = [it.id for it in items]
        if text_ids:
            a_stmt = select(TtsAudio).where(TtsAudio.is_deleted == 0, TtsAudio.text_id.in_(text_ids)).order_by(asc(TtsAudio.version_num))
            audios = s.execute(a_stmt).scalars().all()
            for a in audios:
                audios_map.setdefault(a.text_id, []).append(a)

        selected_text = None
        if selected_id:
            selected_text = s.get(TtsText, int(selected_id))

    # 获取服务
    audio_service = current_app.config['AUDIO_SERVICE']
    pub_url = audio_service.get_audio_url

    return render_template('text_library.html', items=items, audios_map=audios_map, pub_url=pub_url, q=q, order=order, page=page, selected_text=selected_text)


@bp.get('/audios')
def audio_library():
    q = request.args.get('q', '').strip()
    order = request.args.get('order', 'desc')
    page = int(request.args.get('page', 1))
    page_size = 40

    with get_session() as s:
        stmt = select(TtsAudio).where(TtsAudio.is_deleted == 0)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(TtsAudio.filename.like(like))
        stmt = stmt.order_by(desc(TtsAudio.created_at) if order == 'desc' else asc(TtsAudio.created_at))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        items = s.execute(stmt).scalars().all()

    # 获取服务
    audio_service = current_app.config['AUDIO_SERVICE']
    pub_url = audio_service.get_audio_url

    return render_template('audio_library.html', items=items, pub_url=pub_url, q=q, order=order, page=page)


@bp.route('/upload', methods=['GET', 'POST'])
def upload_text():
    if request.method == 'GET':
        # 获取公开配置
        public_config = current_app.config.get('PUBLIC_CONFIG')
        return render_template('upload_text.html', config=public_config)

    # 检查是否为AJAX请求
    is_ajax = request.headers.get('Content-Type') == 'application/json' or request.is_json
    
    auth_enabled = current_app.config.get('AUTH_ENABLED', False)
    user_id = get_current_user_id(auth_enabled, request)

    # 获取数据
    content = ""
    filename = "untitled.txt"
    
    if is_ajax:
        data = request.get_json()
        file_data = data.get('file_data', '')
        title = data.get('title', '').strip()
        content_text = data.get('content', '').strip()
        filename = data.get('filename', 'untitled.txt')
        content = content_text
    else:
        file = request.files.get('file')
        title = request.form.get('title', '').strip()
        content_text = request.form.get('content', '').strip()
        
        if file:
            filename = file.filename or 'unknown.txt'
            if not title:
                title = os.path.splitext(filename)[0]
            stream = io.BytesIO(file.read())
            stream.seek(0)
            text_bytes = stream.read()
            try:
                content = text_bytes.decode('utf-8')
            except Exception:
                content = text_bytes.decode('utf-8', errors='ignore')
        else:
            filename = f"{title or 'untitled'}.txt"
            content = content_text

    if not content:
        if is_ajax:
            return jsonify({
                "success": False,
                "error": "对话内容不能为空",
                "error_type": "validation_error"
            }), 400
        return redirect(url_for('main.upload_text'))
    
    if not title:
        if is_ajax:
            return jsonify({
                "success": False,
                "error": "标题不能为空",
                "error_type": "validation_error"
            }), 400
        return redirect(url_for('main.upload_text'))

    char_count = len(content)

    try:
        # 上传文本到 OSS
        oss = current_app.config['OSS_CLIENT']
        safe_title = title or 'untitled'
        text_object_key = f"texts/{safe_title}/{filename}"
        oss.upload_bytes(text_object_key, content.encode('utf-8'), content_type='text/plain; charset=utf-8')

        # 入库，并异步TTS
        with get_session() as s:
            text_row = TtsText(
                user_id=user_id,
                filename=filename,
                title=safe_title,
                content=content,
                char_count=char_count,
                oss_object_key=text_object_key,
            )
            s.add(text_row)
            s.commit()
            text_id = text_row.id
    except Exception as e:
        print(f"文本上传或入库失败: {e}")
        if is_ajax:
            return jsonify({
                "success": False,
                "error": f"文本保存失败: {str(e)}",
                "error_type": "storage_error"
            }), 500
        return redirect(url_for('main.upload_text'))

    # 一次性幂等检查：若目标音频已存在，则直接返回完成信息，不提交任务
    try:
        import hashlib
        from .tts_client import compute_audio_filename
        audio_filename = compute_audio_filename(safe_title, char_count, 1)
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()[:8]
        audio_object_key = f"audios/{safe_title}/{content_hash}/{audio_filename}"
        audio_exists = oss.object_exists(audio_object_key)
        if audio_exists:
            # 若数据库缺记录，补写一条（文件大小未知置0）
            with get_session() as s:
                existing_audio = s.query(TtsAudio).filter(
                    TtsAudio.text_id == text_id,
                    TtsAudio.oss_object_key == audio_object_key,
                    TtsAudio.is_deleted == 0
                ).first()
                if not existing_audio:
                    audio_row = TtsAudio(
                        text_id=text_id,
                        user_id=user_id,
                        filename=audio_filename,
                        oss_object_key=audio_object_key,
                        file_size=0,
                        version_num=1
                    )
                    s.add(audio_row)
                    s.commit()
            # 生成播放URL并（可选）通知监控器为completed
            audio_service = current_app.config['AUDIO_SERVICE']
            audio_url = audio_service.get_audio_url(audio_object_key)
            monitor = current_app.config.get('MONITOR')
            if monitor:
                try:
                    monitor.complete_task(text_id, audio_url, audio_filename)
                except Exception:
                    pass
            if is_ajax:
                return jsonify({
                    "success": True,
                    "text_id": text_id,
                    "skipped": True,
                    "audio_url": audio_url,
                    "filename": audio_filename,
                    "message": "音频已存在，未重新生成"
                })
            # 非AJAX：重定向到首页
            return redirect(url_for('main.index'))
    except Exception as e:
        # 幂等检查出错则忽略，继续走正常任务提交
        print(f"幂等检查失败，继续提交任务: {e}")

    # 不存在则提交后台任务
    try:
        app_obj = current_app._get_current_object()
        executor.submit(run_tts_and_upload, text_id, user_id, app_obj)
        print(f"对话TTS任务已提交: text_id={text_id}, filename={filename}, char_count={char_count}")
        if is_ajax:
            return jsonify({
                "success": True,
                "text_id": text_id,
                "message": "任务已提交，正在生成音频...",
                "filename": filename,
                "char_count": char_count
            })
    except Exception as e:
        print(f"TTS任务提交失败: {e}")
        if is_ajax:
            return jsonify({
                "success": False,
                "error": f"任务提交失败: {str(e)}",
                "error_type": "task_submission_error"
            }), 500

    # 非AJAX请求重定向到首页
    return redirect(url_for('main.index'))

@bp.route('/settings')
def settings():
    """系统设置页面"""
    public_config = current_app.config.get('PUBLIC_CONFIG')
    return render_template('settings.html', config=public_config)


# ========== 实时音频生成API ==========

@bp.route('/api/task/status/<int:text_id>')
def get_task_status(text_id):
    """获取任务状态"""
    monitor = current_app.config['MONITOR']
    status = monitor.get_task_status(text_id)
    
    if status is None:
        return jsonify({"error": "任务不存在"}), 404
    
    return jsonify(status)


@bp.route('/api/task/stream/<int:text_id>')
def task_stream(text_id):
    """SSE流式推送任务状态"""
    monitor = current_app.config['MONITOR']
    
    def generate_events():
        # 发送初始状态
        initial_status = monitor.get_task_status(text_id)
        if initial_status:
            yield f"data: {json.dumps(initial_status)}\n\n"
        
        # 创建事件监听器
        events = []
        
        def event_listener(event_type, data):
            events.append((event_type, data))
        
        # 添加监听器
        monitor.add_sse_listener(text_id, event_listener)
        
        try:
            # 持续监听事件
            while True:
                if events:
                    event_type, data = events.pop(0)
                    yield f"data: {json.dumps({'event': event_type, **data})}\n\n"
                    
                    # 如果是终态，结束流
                    if event_type in ['completed', 'failed', 'timeout']:
                        break
                else:
                    time.sleep(1)  # 等待1秒
        finally:
            # 清理监听器
            monitor.remove_sse_listener(text_id, event_listener)
    
    return Response(
        generate_events(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Cache-Control'
        }
    )


# ========== 诊断接口 ==========

@bp.get('/api/diagnose/oss')
def diagnose_oss():
    """检查 OSS 鉴权与连通性（只读，不写入）。"""
    try:
        oss = current_app.config['OSS_CLIENT']
        endpoint = getattr(oss, 'endpoint', '')
        bucket_name = getattr(oss, 'bucket_name', '')
        # 只读操作：获取 Bucket 元信息
        info = oss.bucket.get_bucket_info()
        return jsonify({
            "success": True,
            "endpoint": endpoint,
            "bucket": bucket_name,
            "can_get_info": True,
            "region": getattr(info, 'region', None),
            "storage_class": getattr(info, 'storage_class', None),
        })
    except Exception as e:
        logger.exception("OSS诊断失败")
        return jsonify({
            "success": False,
            "endpoint": getattr(current_app.config.get('OSS_CLIENT', object()), 'endpoint', ''),
            "bucket": getattr(current_app.config.get('OSS_CLIENT', object()), 'bucket_name', ''),
            "error": str(e),
        }), 500


@bp.get('/api/diagnose/tts')
def diagnose_tts():
    """检查 TTS WebSocket 鉴权握手（不执行合成）。"""
    try:
        tts_client = current_app.config['TTS_CLIENT']
        app_id_present = bool(getattr(tts_client, 'app_id', None))
        token_present = bool(getattr(tts_client, 'access_token', None))
        endpoint = getattr(tts_client, 'endpoint', '')

        # 在独立事件循环中调用异步 ping
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            res = loop.run_until_complete(tts_client.ping_auth())
        finally:
            loop.close()

        # 确保基本字段存在
        res.setdefault('endpoint', endpoint)
        res.setdefault('app_id_present', app_id_present)
        res.setdefault('token_present', token_present)
        return jsonify(res), (200 if res.get('success') else 500)
    except Exception as e:
        logger.exception("TTS诊断失败")
        return jsonify({
            "success": False,
            "endpoint": getattr(current_app.config.get('TTS_CLIENT', object()), 'endpoint', ''),
            "app_id_present": bool(getattr(current_app.config.get('TTS_CLIENT', object()), 'app_id', None)),
            "token_present": bool(getattr(current_app.config.get('TTS_CLIENT', object()), 'access_token', None)),
            "error": str(e),
        }), 500


@bp.route('/api/task/retry/<int:text_id>', methods=['POST'])
def retry_task(text_id):
    """重试失败的任务"""
    monitor = current_app.config['MONITOR']
    status = monitor.get_task_status(text_id)
    
    if status is None:
        return jsonify({"error": "任务不存在"}), 404
    
    if status['status'] not in ['failed', 'timeout']:
        return jsonify({"error": "只有失败或超时的任务才能重试"}), 400
    
    # 获取用户ID
    auth_enabled = current_app.config.get('AUTH_ENABLED', False)
    user_id = get_current_user_id(auth_enabled, request)
    
    try:
        # 重新提交任务
        executor.submit(run_tts_and_upload, text_id, user_id)
        return jsonify({"success": True, "message": "任务已重新提交"})
    except Exception as e:
        return jsonify({"error": f"重试失败: {str(e)}"}), 500


@bp.route('/api/audio/url/<int:audio_id>')
def get_audio_url(audio_id):
    """获取音频播放URL"""
    with get_session() as s:
        audio = s.get(TtsAudio, audio_id)
        if not audio or audio.is_deleted:
            return jsonify({"error": "音频不存在"}), 404
        
        audio_service = current_app.config['AUDIO_SERVICE']
        audio_url = audio_service.get_audio_url(audio.oss_object_key)
        
        return jsonify({
            "audio_id": audio_id,
            "audio_url": audio_url,
            "filename": audio.filename,
            "file_size": audio.file_size,
            "created_at": audio.created_at.isoformat()
        })


@bp.route('/api/text/title_exists')
def check_title_exists():
    """检查标题是否已存在"""
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify({"error": "标题不能为空"}), 400
    
    with get_session() as s:
        existing_text = s.query(TtsText).filter(
            TtsText.title == title,
            TtsText.is_deleted == 0
        ).first()
        
        return jsonify({
            "exists": existing_text is not None,
            "title": title
        })


@bp.route('/api/debug/task/logs/<int:text_id>')
def get_task_logs(text_id):
    """获取任务调试日志"""
    from .config.logging_config import memory_log_buffer
    
    # 获取该任务的日志
    logs = memory_log_buffer.get_logs(text_id=text_id)
    
    return jsonify({
        "text_id": text_id,
        "logs": logs,
        "count": len(logs)
    })


@bp.route('/api/debug/system/status')
def get_system_status():
    """获取系统状态"""
    from .config.logging_config import memory_log_buffer
    
    monitor = current_app.config['MONITOR']
    stats = monitor.get_stats()
    active_tasks = monitor.get_active_tasks()
    
    return jsonify({
        "monitor_stats": stats,
        "active_tasks": active_tasks,
        "memory_logs_count": len(memory_log_buffer.logs),
        "system_health": "ok"
    })
