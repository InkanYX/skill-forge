# Skill Forge

车棚、凉棚图片制作与团队经验复用工作台。

当前阶段：React + TypeScript + Vite 前端、Python 3.12 + FastAPI 后端。支持个人模型配置、模型列表查询、PostgreSQL 持久化、文字生图、单张参考图编辑、后台任务、结果预览和下载。产品资料库、配方、完整图片编辑器、案例及团队账号尚未实现。

## 环境

- Node.js 24.x（包含 npm）
- Python 3.12，由 uv 管理
- uv
- PostgreSQL 与 Docker 当前不是启动前置条件

## 接入现有 PostgreSQL

已安装 PostgreSQL 容器时，可在后端目录执行：

```powershell
cd D:\project\skill-forge\backend
uv sync --locked
uv run python -m app.database_setup bootstrap --container postgres
```

该命令读取指定容器的本机端口及连接凭据（不在终端显示密码），准备独立的 `skill_forge` 数据库，写入被忽略的 `backend/.env`，执行 Alembic 表结构迁移，再导入旧文件配置。原 JSON 和加密文件保留。已有 DATABASE_URL 时保留原配置；已有 `.env` 但没有数据库配置时不会覆盖文件，请自行按 `.env.example` 补充。

也可以自行在 `backend/.env` 填写 `DATABASE_URL`，随后执行：

```powershell
uv run python -m app.database_setup migrate
uv run python -m app.database_setup check
```

数据库结构由 `backend/migrations/` 管理。后续表结构升级使用 `uv run alembic upgrade head`；旧 JSON 导入只在 setup 命令中显式执行，重复导入不会覆盖数据库中已更新的记录（发现相同 ID 的冲突会取消导入）。应用启动不会自动修改表结构。

后端加载 `.env` 后需重启。`/api/health` 检查服务存活，`/api/system/status` 检查存储连接与配置表是否就绪。设置了数据库但连接失败时，配置 API 返回 503，不会静默切换到文件。

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

当前为**本机单用户开发模式**，尚无团队账号隔离，不应对外开放端口。未设置 DATABASE_URL 时保留文件存储模式；设置后配置保存到 PostgreSQL。连接测试不继承系统 HTTP 代理，不跟随重定向，拒绝本机和内网目标。

### 数据保存与备份

默认数据目录为 `backend/data/`，不随启动工作目录变化。可通过进程环境变量 `SKILL_FORGE_DATA_DIR` 设置绝对路径。

- `model-configs.json`：配置元数据及 Fernet 加密后的密钥。
- `config-encryption.key`：本机解密文件。必须与配置文件一起安全备份；丢失后已有密钥无法恢复。

数据库模式下 `model_configurations` 表保存配置和密文，继续使用原 `config-encryption.key`。备份时应包括数据库、加密文件和 `.env`，安全存放；只有数据库备份无法恢复解密能力。Docker 容器的数据卷也需要备份，删除数据卷会丢失数据库。

文件存储是数据库未就绪时的过渡实现，采用进程内锁和原子替换，当前仅支持一个后端进程。加密文件与数据均位于本机，不能防止拥有完整本机文件权限的人读取。后续迁移至 PostgreSQL 时保留接口契约，并补充账号隔离。请勿随意删除数据目录或只备份其中一个文件。

接口包括 `GET/POST /api/model-configs`、`PUT /api/model-configs/{id}` 和 `POST /api/model-configs/test`。健康检查正常但配置接口返回 404 时，请重启后端加载新代码。

## 验证

```powershell
cd D:\project\skill-forge\frontend
npm run build

cd D:\project\skill-forge\backend
uv run pytest
```

## 多图制作与后台 Worker

表结构更新后，执行 `uv run alembic upgrade head`。另外打开第三个终端运行：

```powershell
cd D:\project\skill-forge\backend
uv run python -m app.worker
```

页面分为“我的工作台”“多图制作”“个人模型配置”，分别通过 `#/`、`#/studio`、`#/settings` 访问，只渲染当前页面；菜单选中状态、顶部标题与浏览器前进后退同步。旧锚点链接仍可打开对应页面。

在“个人模型配置”保存服务商、密钥和模型名称；每份配置对应一个模型，同一服务商可保存多份配置。在“多图制作”下拉选择已保存的模型，填写提示词、尺寸和生成数量（1–8 张，默认 4 张），无需再次填写模型名称。可附一张 PNG/JPEG/WebP 参考图（20 MB、2000 万像素以内）。点击生成才会创建真实调用，每张图片独立使用个人密钥调用服务商并消耗额度。

- 无参考图：`POST <Base URL>/images/generations`，JSON 请求，`n=1`。
- 有参考图：`POST <Base URL>/images/edits`，multipart 请求，字段 `image` 为经过方向校正和去除元数据的 PNG。
- 支持同步 Images 响应中的 `data[0].b64_json` 或公开 HTTPS `url`；下载图片不会携带服务商密钥，不跟随重定向。
- 当前只适配同步 OpenAI Images 协议；仅支持 Responses、Chat Completions 或私有异步协议的服务商，需要后续增加适配器。模型列表可读取不代表生图接口可用。

任务保存到 PostgreSQL `image_jobs` 表，图片位于 `backend/data/image-jobs/<任务ID>/`。刷新页面可恢复任务列表。Worker 每次领取一项任务，其他任务排队；首版先运行一个 Worker。上传素材和任务要求会发送给所选服务商。

多图通过 `POST /api/image-jobs/batch` 一次提交，批内任务在一个数据库事务中创建；每张图片分别生成、展示状态和下载，一张失败不影响其余图片。旧的单张接口仍保留兼容。

提交携带唯一 request_id，重发同一内容、数量与标识返回同一组任务。提交响应不明确时，页面保留标识并锁定输入；先核对列表，再决定重发或修改。任务保存了服务商和模型配置的加密快照，排队后修改配置不会改变原任务。终态任务清除其临时密钥密文。

执行成功后提供预览和 PNG 下载。超时、连接中断、返回不明或下载异常标为 `unknown`，不自动再次调用。Worker 异常退出时，运行任务在 15 分钟租约到期后由下一次队列检查标记未知，不自动重新排队；请先核对服务商记录。已排队且尚未执行的任务可在 Worker 重启后继续。

文件保存与数据库不构成同一事务；极端中断可能留下未关联文件或未知任务，原文件保留供核对。当前无自动清理或删除功能。数据库备份需要同时备份图片目录与加密文件。

测试使用模拟服务商和虚构密钥，不自动调用真实付费模型；可用 `SKILL_FORGE_TEST_POSTGRES=1` 显式启用本机 PostgreSQL 集成验证。

`npm run build` 包含 TypeScript 检查。前端产物位于 `frontend/dist`。Python 使用后端目录下的 `.venv`。依赖版本由 `package-lock.json` 和 `uv.lock` 锁定；首次准备环境需要联网下载依赖。

## 后续接入

### 创作模板与案例库（已实现）

菜单使用“图片创作”“创作模板”“案例库”和“个人模型配置”。在创作模板中新建制作方法，可从“凉棚 · 庭院场景”或“车棚 · 产品展示”示例开始，保存用途、画面要求、默认尺寸/数量及注意事项。用 `{{产品名称}}`、`{{颜色}}` 等占位符定义产品信息，创作时自动生成必填项。Skill 支持粘贴或导入 Markdown/TXT（100 KB 内、20000 字符内），作为自然语言指令合并进请求，不执行代码或自动多步骤 Agent 流程。

保存模板后点击“使用此模板”，在图片创作页填写产品信息，选择自己的模型配置并上传可选参考图。服务端渲染最终制作要求，保存完整模板版本、Skill、填写值与补充要求到每张任务的 `template_snapshot`。模板修改使用版本冲突检查，历史任务和案例始终保留当时的版本；重复提交仍复用原有任务。

生成成功后，可在结果区“保存为成功案例”填写标题、有效经验和问题。案例库支持搜索、预览、查看原始制作要求，以及使用关联模板的最新版本。每张图片只保存一份案例，再次保存会更新经验。新表为 `creative_templates`、`creative_cases`，更新已有环境后运行 `uv run alembic upgrade head`；本次开发已迁移本机数据库。当前仍是本机单人阶段，未提供团队账号权限。

1. 产品/素材数据模型与上传管理。
2. 增加服务商协议适配与图片局部编辑。
3. Skill 的多步骤任务流程与质量检查。
4. 图片编辑、案例管理与团队权限。

业务模块逐步放入 `backend/app`，前端代码位于 `frontend/src`。图片数据未来放入独立目录，数据库、密钥与图片不提交到代码仓库。
