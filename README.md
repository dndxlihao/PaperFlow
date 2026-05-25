# PaperFlow

一个面向学术协作与内容沉淀的论文平台：检索、阅读、推荐、讨论、创作者投稿与后台审核一体化。

## 项目亮点

- 多源论文流：系统论文库、每日推荐、知识库检索、创作者投稿。
- AI 内容增强：基于论文内容生成中文总结、关键词、图示解读。
- 社区互动：评论、回复、点赞、@提醒、站内通知。
- 协作治理：创作者投稿审核、卡片纠错审核、管理员后台运营面板。
- 数据化运营：推荐任务状态、热门卡片、偏好统计、知识热点追踪。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18 + Vite + React Router + Axios |
| 后端 | Flask + SQLAlchemy + APScheduler |
| 数据库 | MySQL |
| AI 接入 | OpenAI SDK（兼容 DeepSeek Base URL） |
| 抓取与处理 | requests / selenium / pdfplumber |
| 认证 | JWT |

## 目录结构

```text
wechat/
├── backend/
│   ├── app.py                 # Flask 启动与蓝图注册
│   ├── models.py              # 数据模型
│   ├── auth.py                # 登录注册/JWT
│   ├── papers.py              # 论文、评论、创作者投稿相关 API
│   ├── recommend.py           # 推荐逻辑与策略
│   ├── knowledge.py           # 知识库/RAG/热点追踪
│   ├── admin.py               # 管理员后台 API
│   ├── scheduler.py           # 定时任务
│   ├── daily_update.py        # 每日推荐数据更新
│   └── config.py              # 配置读取
├── frontend/
│   ├── src/
│   │   ├── pages/             # 页面
│   │   ├── components/        # 组件
│   │   └── api/               # 请求封装
│   └── package.json
├── main.py                    # 旧版接口入口（保留）
└── README.md
```

## 快速启动

### 1) 准备数据库

```sql
CREATE DATABASE paper_hub CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 2) 后端配置

```bash
cd backend
cp .env.example .env
```

至少需要配置以下变量：

- `DATABASE_URL`
- `SECRET_KEY`
- `DEEPSEEK_API_KEY`（或其他兼容 OpenAI SDK 的密钥）
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`

安装依赖：

```bash
pip install -r requirements.txt
```

### 3) 启动后端

```bash
cd backend
python app.py
```

默认地址：`http://localhost:5001`

### 4) 启动前端

```bash
cd frontend
npm install
npm run dev
```

默认地址：`http://localhost:3000`  
前端通过 Vite 代理将 `/api` 转发到 `5001`。

## 协作开发约定

- 代码仓库仅提交“功能代码与必要配置模板”。
- 论文 PDF、用户隐私数据、缓存与运行产物不入库。
- 新成员请先复制 `backend/.env.example` 为本地 `backend/.env`。

本仓库已通过 `.gitignore` 排除以下敏感/大体积目录与文件：

- `docs/`、`figures/`、`backend/docs/`
- `pic/avatars/`
- `backend/embeddings_cache.npz`
- `backend/knowledge_trends_cache.json`
- `.env` / `backend/.env`

## 常用命令

```bash
# 后端
cd backend && python app.py

# 前端开发
cd frontend && npm run dev

# 前端打包
cd frontend && npm run build
```

## 许可证

当前仓库未附加开源许可证。若计划对外开源，建议补充 `LICENSE`（如 MIT / Apache-2.0）。
