# 开发指南

## 开发环境搭建

### 1. 环境要求
- Python 3.10+
- MySQL 8+
- Git
- 代码编辑器（推荐VS Code）

### 2. 项目克隆
```bash
git clone [项目地址]
cd tts_vocl
```

### 3. 虚拟环境
```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
source .venv/bin/activate  # macOS/Linux
# 或
.venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 4. 数据库设置
```bash
# 创建数据库
mysql -u root -p -e "CREATE DATABASE tts_vocl CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"

# 执行建表脚本
mysql -u root -p tts_vocl < schema.sql
```

### 5. 配置文件
在项目外层父目录创建 `db_config.json`：
```json
{
  "AUTH_ENABLED": false,
  "MYSQL": {
    "HOST": "127.0.0.1",
    "PORT": 3306,
    "USER": "root",
    "PASSWORD": "your_password",
    "DB": "tts_vocl"
  },
  "OSS": {
    "ENDPOINT": "https://oss-cn-shanghai.aliyuncs.com",
    "BUCKET": "your_bucket",
    "ACCESS_KEY_ID": "your_key",
    "ACCESS_KEY_SECRET": "your_secret"
  },
  "VOLC_TTS": {
    "APP_ID": "your_app_id",
    "ACCESS_TOKEN": "your_token",
    "SECRET_KEY": "your_secret",
    "API_BASE": "https://open.volcengineapi.com"
  }
}
```

### 6. 启动开发服务器
```bash
export FLASK_ENV=development
python run_refactored_app.py
```

## 代码规范

### 1. Python代码规范
- 使用PEP 8风格
- 函数和类添加文档字符串
- 变量命名使用下划线分隔
- 常量使用大写字母

```python
def process_upload_file(file_data: bytes, filename: str) -> dict:
    """
    处理上传的文件
    
    Args:
        file_data: 文件二进制数据
        filename: 文件名
    
    Returns:
        处理结果字典
    """
    # 实现代码
    pass
```

### 2. 数据库规范
- 表名使用`tts_`前缀
- 字段名使用下划线分隔
- 必须包含`created_at`、`updated_at`、`is_deleted`字段
- 使用软删除而非硬删除

```sql
CREATE TABLE tts_example (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_deleted TINYINT(1) DEFAULT 0
);
```

### 3. 前端规范
- HTML使用语义化标签
- CSS使用Tailwind CSS类名
- JavaScript使用ES6+语法
- 事件处理使用addEventListener

```html
<div class="bg-white border rounded p-4">
    <button id="submit-btn" class="px-4 py-2 bg-blue-600 text-white rounded">
        提交
    </button>
</div>

<script>
document.getElementById('submit-btn').addEventListener('click', function() {
    // 处理逻辑
});
</script>
```

## 开发流程

### 1. 功能开发流程
1. **需求分析**：明确功能需求和技术要求
2. **设计阶段**：数据库设计、API设计、UI设计
3. **编码实现**：后端逻辑、前端界面、数据库操作
4. **测试验证**：功能测试、性能测试、兼容性测试
5. **代码审查**：代码质量检查、安全审查
6. **部署上线**：测试环境验证、生产环境部署

### 2. 分支管理
```bash
# 主分支
main                    # 生产环境代码

# 开发分支
develop                 # 开发环境代码
feature/功能名称        # 功能开发分支
bugfix/问题描述         # 问题修复分支
hotfix/紧急修复         # 紧急修复分支
```

### 3. 提交规范
```bash
# 提交信息格式
<类型>(<范围>): <描述>

# 类型说明
feat:     新功能
fix:      修复问题
docs:     文档更新
style:    代码格式调整
refactor: 代码重构
test:     测试相关
chore:    构建过程或辅助工具的变动

# 示例
feat(upload): 添加文件拖拽上传功能
fix(audio): 修复音频播放器兼容性问题
docs(api): 更新API文档
```

## 调试技巧

### 1. Flask调试
```python
# 启用调试模式
export FLASK_ENV=development
export FLASK_DEBUG=1

# 在代码中添加断点
import pdb; pdb.set_trace()

# 使用Flask调试器
from flask import current_app
current_app.logger.debug("调试信息")
```

### 2. 数据库调试
```python
# 查看SQL语句
from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "before_cursor_execute")
def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    print("SQL:", statement)
    print("参数:", parameters)
```

### 3. 前端调试
```javascript
// 控制台调试
console.log("调试信息", data);

// 网络请求调试
fetch('/api/upload', {
    method: 'POST',
    body: formData
}).then(response => {
    console.log('响应状态:', response.status);
    return response.json();
}).then(data => {
    console.log('响应数据:', data);
});
```

## 测试策略

### 1. 单元测试
```python
import unittest
from app import create_app
from app.models import TtsText

class TestTtsText(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
    
    def test_create_text(self):
        # 测试文本创建
        pass
```

### 2. 集成测试
```python
def test_upload_workflow():
    # 测试完整的上传流程
    # 1. 上传文件
    # 2. 验证数据库记录
    # 3. 验证TTS任务
    # 4. 验证音频生成
    pass
```

### 3. 性能测试
```python
import time
import requests

def test_upload_performance():
    start_time = time.time()
    response = requests.post('http://localhost:8082/upload', data=form_data)
    end_time = time.time()
    
    assert response.status_code == 200
    assert end_time - start_time < 2.0  # 响应时间小于2秒
```

## 部署指南

### 1. 生产环境配置
```python
# 生产环境配置
app.config.update(
    DEBUG=False,
    TESTING=False,
    SECRET_KEY='production-secret-key'
)
```

### 2. 使用Gunicorn
```bash
# 安装Gunicorn
pip install gunicorn

# 启动生产服务器
gunicorn -w 4 -b 0.0.0.0:8082 run_refactored_app:app
```

### 3. 使用Nginx反向代理
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://127.0.0.1:8082;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    location /static {
        alias /path/to/tts_vocl/static;
    }
}
```

### 4. 数据库备份
```bash
# 创建备份脚本
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
mysqldump -u root -p tts_vocl > backup_${DATE}.sql

# 定时备份（crontab）
0 2 * * * /path/to/backup_script.sh
```

## 监控和日志

### 1. 应用监控
```python
import logging
from logging.handlers import RotatingFileHandler

# 配置日志
if not app.debug:
    file_handler = RotatingFileHandler('logs/tts_vocl.log', maxBytes=10240, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
```

### 2. 性能监控
```python
import time
from functools import wraps

def monitor_performance(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        
        print(f"{func.__name__} 执行时间: {end_time - start_time:.2f}秒")
        return result
    return wrapper
```

### 3. 错误监控
```python
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

# 配置Sentry错误监控
sentry_sdk.init(
    dsn="your-sentry-dsn",
    integrations=[FlaskIntegration()],
    traces_sample_rate=1.0
)
```

## 常见问题

### 1. 配置文件问题
**问题**：`JSONDecodeError: Expecting value`
**解决**：检查配置文件JSON格式，确保没有注释

### 2. 数据库连接问题
**问题**：`OperationalError: (2003, "Can't connect to MySQL server")`
**解决**：检查MySQL服务状态和连接参数

### 3. OSS上传失败
**问题**：`OSSError: Access denied`
**解决**：检查OSS凭据和Bucket权限

### 4. TTS任务失败
**问题**：异步任务执行失败
**解决**：查看任务日志，检查TTS服务配置

## 贡献指南

### 1. 提交代码
1. Fork项目仓库
2. 创建功能分支
3. 提交代码变更
4. 创建Pull Request

### 2. 代码审查
- 检查代码质量和规范
- 验证功能正确性
- 确保测试覆盖率
- 检查安全性问题

### 3. 文档更新
- 更新API文档
- 完善开发指南
- 添加变更日志

---

*最后更新：2025-09-03*
*版本：v1.0.0*
