# 失败任务重试功能文档

> 作者：蘑菇🍄  
> 日期：2025-10-13  
> 版本：v1.0

## 📋 功能概述

本文档说明失败任务重试功能的实现，该功能允许用户在首页直接重试失败的TTS任务，提升用户体验和系统可用性。

---

## 🎯 核心功能

### 1️⃣ **真实任务状态显示**
- ✅ **处理中**：显示"⏳ 处理中..."和"查看进度"链接
- ✅ **失败/超时**：显示"❌ 任务失败"和"🔄 重试"按钮
- ✅ **未生成**：显示"未生成音频"和"生成音频"按钮
- ✅ **已完成**：显示音频播放器和下载链接

### 2️⃣ **一键重试**
- ✅ 点击重试按钮立即提交任务
- ✅ 实时显示任务进度（SSE推送）
- ✅ 任务完成后自动刷新显示音频
- ✅ 失败后可再次重试

### 3️⃣ **数据一致性保护**
- ✅ 数据库唯一约束防止重复记录
- ✅ 多层检查防止并发冲突
- ✅ 幂等性保证任务安全

---

## 🔧 技术实现

### 1. 数据库修改

#### 添加唯一约束
```sql
-- 确保同一 text_id 在未删除状态下只有一条音频记录
ALTER TABLE tts_audios 
ADD CONSTRAINT uq_tts_audios_text_id_active 
UNIQUE (text_id, is_deleted);
```

**重要提示**：
- ⚠️ 执行前需检查是否有重复记录
- ⚠️ 迁移脚本位于 `migrations/add_text_id_unique_constraint.sql`
- ⚠️ 需要在生产环境执行此迁移

#### 检查重复记录
```sql
SELECT text_id, COUNT(*) as count
FROM tts_audios
WHERE is_deleted = 0
GROUP BY text_id
HAVING count > 1;
```

#### 清理重复记录（如果有）
```sql
-- 保留最新的记录，删除旧记录
DELETE a1 FROM tts_audios a1
INNER JOIN tts_audios a2 
WHERE a1.text_id = a2.text_id 
  AND a1.is_deleted = 0 
  AND a2.is_deleted = 0
  AND a1.id < a2.id;
```

---

### 2. 后端实现

#### 修改文件：`app/models.py`
```python
class TtsAudio(Base):
    __table_args__ = (
        UniqueConstraint('oss_object_key', name='uq_tts_audios_oss_object_key'),
        UniqueConstraint('text_id', 'is_deleted', name='uq_tts_audios_text_id_active'),  # 新增
    )
```

#### 修改文件：`app/views.py`

**1. 首页传递任务状态**
```python
@bp.get('/')
def index():
    # ... 原有代码 ...
    
    # 获取任务状态
    monitor = current_app.config['MONITOR']
    task_status_map = {}
    for text in items:
        status = monitor.get_task_status(text.id)
        if status:
            task_status_map[text.id] = status
    
    return render_template('text_library.html', 
                         task_status_map=task_status_map,  # 新增
                         ...)
```

**2. 新增重试API**
```python
@bp.post('/api/task/retry/<int:text_id>')
def retry_task(text_id: int):
    """重试失败的TTS任务"""
    # 1. 检查是否已有进行中的任务
    # 2. 检查数据库是否已有音频
    # 3. 提交后台任务
```

**多层防护机制**：
- ✅ 检查TaskMonitor是否有进行中任务
- ✅ 检查数据库是否已有音频记录
- ✅ 幂等性保证（TaskService层）

---

### 3. 前端实现

#### 修改文件：`templates/text_library.html`

**1. 状态显示逻辑**
```html
{% if audios_map.get(it.id, []) %}
    <!-- 有音频：显示播放器 -->
{% elif task_status_map.get(it.id) %}
    {% if task.status == 'processing' %}
        <!-- 处理中：显示进度 -->
    {% elif task.status == 'failed' or task.status == 'timeout' %}
        <!-- 失败：显示重试按钮 -->
    {% endif %}
{% else %}
    <!-- 未开始：显示生成按钮 -->
{% endif %}
```

**2. 重试逻辑**
```javascript
async function retryTask(textId) {
    // 1. 禁用按钮
    // 2. 发送重试请求
    // 3. 显示处理中状态
    // 4. 启动SSE监控
}
```

**3. SSE监控**
```javascript
function startTaskMonitoring(textId, container) {
    const eventSource = new EventSource(`/api/task/stream/${textId}`);
    
    eventSource.onmessage = function(event) {
        if (data.status === 'completed') {
            location.reload();  // 刷新显示音频
        } else if (data.status === 'failed') {
            // 显示失败和重试按钮
        }
    };
}
```

---

## 📊 用户交互流程

```
用户在首页看到任务状态
    ↓
[情况1] 有音频 → 显示播放器
[情况2] 处理中 → 显示"⏳ 处理中..."
[情况3] 失败 → 显示"❌ 任务失败" + "🔄 重试"
[情况4] 未生成 → 显示"未生成音频" + "生成音频"
    ↓
用户点击"🔄 重试"或"生成音频"
    ↓
前端：
  - 禁用按钮
  - 发送POST /api/task/retry/{text_id}
    ↓
后端检查：
  - 任务是否进行中？→ 返回409
  - 音频是否已存在？→ 返回200
  - 都没有？→ 提交任务
    ↓
前端：
  - 显示"⏳ 处理中..."
  - 启动SSE监控
    ↓
SSE实时推送状态：
  - processing → 继续等待
  - completed → 刷新页面显示音频
  - failed → 显示失败和重试按钮
```

---

## ⚠️ 重要注意事项

### 1. 数据库迁移 🚨
**必须在重启服务前执行数据库迁移！**

```bash
# 1. 备份数据库
mysqldump -u user -p database_name > backup_$(date +%Y%m%d).sql

# 2. 检查重复记录
mysql -u user -p database_name < migrations/add_text_id_unique_constraint.sql

# 3. 如有重复，先清理
# 参考迁移脚本中的清理SQL

# 4. 执行迁移
ALTER TABLE tts_audios ADD CONSTRAINT uq_tts_audios_text_id_active UNIQUE (text_id, is_deleted);
```

### 2. 兼容性
- ✅ 向后兼容：不影响现有功能
- ✅ 优雅降级：即使SSE失败也能手动刷新
- ✅ 防护完善：多层检查防止数据不一致

### 3. 性能考虑
- ✅ TaskMonitor内存查询：毫秒级响应
- ✅ 数据库索引：text_id已有外键索引
- ✅ SSE连接：30秒自动关闭，防止占用

---

## 🧪 测试场景

### 场景1：正常重试
```
1. 找到失败任务
2. 点击"🔄 重试"
3. 等待任务完成
4. 页面自动刷新显示音频
```

### 场景2：重复点击防护
```
1. 点击"🔄 重试"
2. 按钮禁用变为"重试中..."
3. 再次点击无效
4. 任务完成后恢复
```

### 场景3：任务已在进行中
```
1. 任务正在处理中
2. 点击"🔄 重试"
3. 返回409，显示"处理中"
4. 自动启动SSE监控
```

### 场景4：音频已存在
```
1. 音频已生成但页面未刷新
2. 点击"🔄 重试"
3. 返回"音频已存在"
4. 自动刷新页面显示音频
```

### 场景5：并发重试
```
1. 多个用户同时重试同一任务
2. 只有一个任务执行
3. 其他请求返回"任务进行中"或"音频已存在"
4. 数据一致性得到保证
```

---

## 📝 代码变更统计

| 文件 | 变更类型 | 行数 |
|------|---------|------|
| `app/models.py` | 新增约束 | 1 |
| `app/views.py` | 新增功能 | 74 |
| `templates/text_library.html` | 新增UI和逻辑 | 140 |
| `migrations/add_text_id_unique_constraint.sql` | 新增 | 30 |
| **总计** | - | **245** |

---

## 🔍 故障排查

### 问题1：重试按钮点击无反应
**排查**：
```javascript
// 浏览器控制台查看
console.log('重试请求:', textId);
// 检查网络请求
```

**解决**：
- 检查按钮ID是否正确
- 检查JavaScript是否加载
- 检查网络请求是否成功

### 问题2：任务提交后无进度显示
**排查**：
```bash
# 检查SSE端点
curl http://localhost:8082/api/task/stream/123
```

**解决**：
- 检查TaskMonitor是否正常
- 检查SSE连接是否建立
- 检查浏览器控制台错误

### 问题3：数据库约束冲突
**现象**：
```
IntegrityError: Duplicate entry for key 'uq_tts_audios_text_id_active'
```

**排查**：
```sql
SELECT * FROM tts_audios 
WHERE text_id = 123 AND is_deleted = 0;
```

**解决**：
- 检查是否有重复记录
- 删除旧记录或标记为已删除

---

## 📚 相关文档

- [并发优化文档](./CONCURRENT_OPTIMIZATION.md)
- [API参考文档](./API_REFERENCE.md)
- [开发指南](./DEVELOPMENT_GUIDE.md)

---

**作者：蘑菇🍄**  
**最后更新：2025-10-13**

