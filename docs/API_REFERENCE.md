# API 参考文档

## 路由列表

### 页面路由

| 路由 | 方法 | 描述 | 参数 |
|------|------|------|------|
| `/` | GET | 文本资源库首页 | `q`(搜索), `order`(排序), `page`(页码), `selected_id`(选中文本) |
| `/audios` | GET | 音频资源库 | `q`(搜索), `order`(排序), `page`(页码) |
| `/upload` | GET | 上传文本页面 | - |
| `/upload` | POST | 处理文件上传 | `file`(文件), `title`(标题), `content`(内容) |

### 请求参数

#### GET / (文本资源库)
- `q` (string, optional): 搜索关键词，支持标题和上传者搜索
- `order` (string, optional): 排序方式，`desc`(降序) 或 `asc`(升序)，默认`desc`
- `page` (int, optional): 页码，默认1
- `selected_id` (int, optional): 选中的文本ID，用于预览

#### GET /audios (音频资源库)
- `q` (string, optional): 搜索关键词，支持标题和生成者搜索
- `order` (string, optional): 排序方式，`desc`(降序) 或 `asc`(升序)，默认`desc`
- `page` (int, optional): 页码，默认1

#### POST /upload (文件上传)
- `file` (file, optional): 上传的.txt文件
- `title` (string, optional): 文本标题，默认使用文件名
- `content` (string, required): 文本内容

## 数据模型

### TtsUser (用户)
```python
{
    "id": int,                    # 主键
    "unified_user_id": str,       # 统一用户ID
    "name": str,                  # 用户名
    "email": str,                 # 邮箱
    "avatar_url": str,            # 头像URL
    "platform": str,              # 登录平台
    "platform_user_id": str,      # 平台用户ID
    "created_at": datetime,       # 创建时间
    "updated_at": datetime,       # 更新时间
    "is_deleted": int             # 软删除标志
}
```

### TtsText (文本)
```python
{
    "id": int,                    # 主键
    "user_id": int,               # 用户ID
    "filename": str,              # 文件名
    "title": str,                 # 标题
    "content": str,               # 内容
    "char_count": int,            # 字数
    "oss_object_key": str,        # OSS对象键
    "created_at": datetime,       # 创建时间
    "updated_at": datetime,       # 更新时间
    "is_deleted": int             # 软删除标志
}
```

### TtsAudio (音频)
```python
{
    "id": int,                    # 主键
    "text_id": int,               # 文本ID
    "user_id": int,               # 用户ID
    "filename": str,              # 文件名
    "oss_object_key": str,        # OSS对象键
    "duration_sec": int,          # 时长(秒)
    "file_size": int,             # 文件大小
    "version_num": int,           # 版本号
    "created_at": datetime,       # 创建时间
    "updated_at": datetime,       # 更新时间
    "is_deleted": int             # 软删除标志
}
```

## 响应格式

### 成功响应
所有页面路由返回HTML模板，包含以下数据：

#### 文本资源库响应
```python
{
    "items": List[TtsText],       # 文本列表
    "audios_map": Dict[int, List[TtsAudio]],  # 文本对应的音频映射
    "pub_url": function,          # OSS公开URL生成函数
    "q": str,                     # 搜索关键词
    "order": str,                 # 排序方式
    "page": int,                  # 当前页码
    "selected_text": TtsText      # 选中的文本(可选)
}
```

#### 音频资源库响应
```python
{
    "items": List[TtsAudio],      # 音频列表
    "pub_url": function,          # OSS公开URL生成函数
    "q": str,                     # 搜索关键词
    "order": str,                 # 排序方式
    "page": int                   # 当前页码
}
```

### 错误响应
- **400 Bad Request**: 请求参数错误
- **404 Not Found**: 资源不存在
- **500 Internal Server Error**: 服务器内部错误

## 异步任务

### TTS生成任务
```python
def run_tts_and_upload(oss_client, tts_client, text_id, user_id, base_name_no_ext, char_count):
    """
    异步TTS生成任务
    
    参数:
        oss_client: OSS客户端实例
        tts_client: TTS客户端实例
        text_id: 文本ID
        user_id: 用户ID
        base_name_no_ext: 文件名(无扩展名)
        char_count: 字数
    
    流程:
        1. 计算版本号
        2. 获取文本内容
        3. TTS合成
        4. 上传到OSS
        5. 保存到数据库
    """
```

## 配置接口

### 应用配置
```python
app.config = {
    'AUTH_ENABLED': bool,         # 鉴权开关
    'JWT_SECRET_KEY': str,        # JWT密钥
    'JWT_ACCESS_TOKEN_EXPIRES': int,  # JWT过期时间
    'OSS_CLIENT': OssClient,      # OSS客户端
    'TTS_CLIENT': VolcTtsClient   # TTS客户端
}
```

### 数据库配置
```python
mysql_config = {
    'HOST': str,                  # 数据库主机
    'PORT': int,                  # 端口
    'USER': str,                  # 用户名
    'PASSWORD': str,              # 密码
    'DB': str,                    # 数据库名
    'POOL_SIZE': int,             # 连接池大小
    'POOL_TIMEOUT': int,          # 连接超时
    'POOL_RECYCLE': int           # 连接回收时间
}
```

## 工具函数

### OSS URL生成
```python
def public_url(object_key: str) -> str:
    """
    生成OSS公开访问URL
    
    参数:
        object_key: OSS对象键
    
    返回:
        公开访问URL
    """
```

### 音频文件名生成
```python
def compute_audio_filename(base_name_no_ext: str, char_count: int, next_version: int) -> str:
    """
    计算音频文件名
    
    参数:
        base_name_no_ext: 基础文件名(无扩展名)
        char_count: 字数
        next_version: 版本号
    
    返回:
        格式化的音频文件名
    """
```

## 错误处理

### 异常类型
- `JSONDecodeError`: 配置文件解析错误
- `SQLAlchemyError`: 数据库操作错误
- `OSSError`: OSS操作错误
- `TTSClientError`: TTS服务错误

### 日志记录
```python
# 应用日志
print(f"TTS任务已提交: text_id={text_id}, filename={filename}")

# 任务日志
print(f"开始TTS任务: text_id={text_id}, user_id={user_id}")
print(f"TTS任务完成: audio_id={audio.id}, filename={filename}")

# 错误日志
print(f"TTS任务失败: text_id={text_id}, error={e}")
```

## 性能指标

### 响应时间
- 页面加载: < 500ms
- 文件上传: < 2s
- TTS生成: 异步处理

### 并发处理
- 线程池大小: 4
- 队列容量: 64
- 数据库连接池: 10

### 资源限制
- 文件大小: ≤ 5MB
- 文本长度: 无限制(建议< 10000字)
- 版本数量: ≤ 99

---

*最后更新：2025-09-03*
*版本：v1.0.0*
