# Skill Forge

车棚、凉棚图片制作与团队经验复用工作台。

当前阶段：React + TypeScript + Vite 前端、Python 3.12 + FastAPI 后端。支持个人模型配置的新建、编辑、保存、模型列表查询和健康检查。素材、生图、数据库、Worker、账号和配方功能尚未实现。

## 环境

- Node.js 24.x（包含 npm）
- Python 3.12，由 uv 管理
- uv
- PostgreSQL 与 Docker 当前不是启动前置条件

如果终端提示找不到 npm，先用 `node --version` 和 `npm --version` 检查。使用 nvm 时确认已启用 Node 24；安装后重新打开终端。项目不依赖全局 React/Vite。

## 启动后端

在 PowerShell 中：

```powershell
cd D:\project\skill-forge\backend
uv sync --locked
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- 健康检查：http://127.0.0.1:8000/api/health
- 接口文档：http://127.0.0.1:8000/docs

## 启动前端

另外打开一个 PowerShell：

```powershell
cd D:\project\skill-forge\frontend
npm ci
npm run dev
```

打开 http://127.0.0.1:5173 。后端运行时，首页应显示“后端连接正常”；后端关闭时显示连接失败，并可手动重新检查。

Vite 将 `/api` 代理到 `http://127.0.0.1:8000`。如需修改，复制 `frontend/.env.example` 为 `frontend/.env.local` 并调整 `API_PROXY_TARGET`，然后重启前端开发服务。生产环境应由反向代理转发 `/api`，Vite 开发代理只在开发模式工作。

所有开发服务仅监听本机地址。API Key 在“个人模型配置”页面输入，经本机后端加密保存；不返回原文，不写入浏览器 localStorage，不进入代码仓库。不要将密钥写入前端环境变量。

## 个人模型配置

1. 页面中填写配置名称、公开 HTTPS Base URL 和 API Key。根地址会补 `/v1`，已有自定义路径会保留。首版连接测试仅支持 HTTPS 443 端口和公网 IPv4。
2. 点击“测试连接 / 读取模型”，后端请求 `GET <Base URL>/models`，使用 Bearer 认证。不会提交生成请求或上传图片，也不会自动保存未保存的配置。
3. 模型列表查询成功后可以点击模型，或手动输入模型 ID。服务商不支持模型列表时仍可保存，但认证与生图能力保持未验证状态。
4. 点击“保存配置”。刷新页面后点击已保存的配置可继续编辑。密钥留空表示保留旧值；改变地址时必须重新输入密钥。

当前为**本机单用户开发模式**，尚无团队账号隔离，不应对外开放端口。模型配置不依赖 Docker/PostgreSQL。连接测试不继承系统 HTTP 代理，不跟随重定向，拒绝本机和内网目标。

### 数据保存与备份

默认数据目录为 `backend/data/`，不随启动工作目录变化。可通过进程环境变量 `SKILL_FORGE_DATA_DIR` 设置绝对路径。

- `model-configs.json`：配置元数据及 Fernet 加密后的密钥。
- `config-encryption.key`：本机解密文件。必须与配置文件一起安全备份；丢失后已有密钥无法恢复。

文件存储是数据库未就绪时的过渡实现，采用进程内锁和原子替换，当前仅支持一个后端进程。加密文件与数据均位于本机，不能防止拥有完整本机文件权限的人读取。后续迁移至 PostgreSQL 时保留接口契约，并补充账号隔离。请勿随意删除数据目录或只备份其中一个文件。

接口包括 `GET/POST /api/model-configs`、`PUT /api/model-configs/{id}` 和 `POST /api/model-configs/test`。健康检查正常但配置接口返回 404 时，请重启后端加载新代码。

## 验证

```powershell
cd D:\project\skill-forge\frontend
npm run build

cd D:\project\skill-forge\backend
uv run pytest
```

`npm run build` 包含 TypeScript 检查。前端产物位于 `frontend/dist`。Python 使用后端目录下的 `.venv`。依赖版本由 `package-lock.json` 和 `uv.lock` 锁定；首次准备环境需要联网下载依赖。

## 后续接入

1. PostgreSQL 迁移与产品/素材模型。
2. 在现有接口配置基础上接入真实生图与编辑。
3. 配方、自然语言 Skill 与任务 Worker。
4. 图片编辑、案例管理与团队权限。

业务模块逐步放入 `backend/app`，前端代码位于 `frontend/src`。图片数据未来放入独立目录，数据库、密钥与图片不提交到代码仓库。
