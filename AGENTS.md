# Project Instructions

## Language

代码：

English

注释：

Chinese where necessary

文档：

Chinese

---

## Python

Python >= 3.12

必须使用：

async / await

FastAPI

SQLAlchemy 2.x

Pydantic

禁止使用：

同步 requests

优先：

httpx.AsyncClient

---

## Architecture

必须遵守：

API
↓
Service
↓
Repository

API 禁止直接访问 DB。

---

## Task Architecture

所有任务必须继承：

BaseTask

任务必须通过：

TaskRegistry

注册。

禁止：

if task_code == ...

---

## Adapter

所有外部系统必须 Adapter 化。

例如：

OneBot
Playwright
Mobile

业务 Task 禁止直接请求第三方 HTTP。

---

## Error Handling

禁止：

except Exception:
pass

所有异常：

记录日志

转换业务错误。

---

## Security

禁止记录：

password
token
cookie
session
authorization

禁止把 secret 写入 Git。

---

## Test

每增加一个功能：

必须增加 pytest。

修改 TaskEngine：

必须运行完整 task tests。

修改 Repository：

必须运行 database tests。

---

## Development

完成任务前：

1. 阅读现有代码
2. 理解架构
3. 制定修改计划
4. 修改代码
5. 执行测试
6. 修复失败
7. 再汇报

禁止只写代码不测试。

---

## Output

每次任务完成后告诉用户：

### 完成内容

### 修改文件

### 数据库变化

### API变化

### 测试结果

### 尚未完成
