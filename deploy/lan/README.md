# 新版局域网部署

代码目录：`D:\project\skill-forge-main`；入口：`http://192.168.19.136:8080`。

后台任务：`SkillForge-API` 与 `SkillForge-Web`；开机和 admin 登录时触发，异常退出后重启。Docker Desktop 仍需要 admin 登录后启动。

## 线上数据与开发数据分离

线上环境由 `common.ps1` 读取 `.lan-runtime/deployment.env`，覆盖进程的 `DATABASE_URL` 和 `SKILL_FORGE_DATA_DIR`。**直接运行 uv / Alembic 不会自动读取线上配置**，可能操作原有测试数据库。

- 线上数据库：`skill_forge_lan_v2`，由原 `skill_forge` 数据库完整复制后兼容升级。
- 线上图片及原密钥：`.lan-runtime/shared-data/`，由旧版 `backend/data/` 原样复制。
- 新版原有 `backend/.env`、`backend/data/` 和 `skill_forge_main_test` 保留作为开发测试环境。
- 旧版原数据库、目录与数据保留；兼容迁移不修改原数据库。
- 切换前完整备份：`.lan-runtime/backups/`，包含 PostgreSQL dump、图片/密钥 ZIP 和旧版环境配置。仅 admin、管理员组及 SYSTEM 可访问运行目录。
- 旧版 `product_image_projects` 表保留在新数据库中，但新版使用不同的创作项目结构，未将旧草稿强行转换为新项目。

## 查看状态

```powershell
cd D:\project\skill-forge-main
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\deploy\lan\status.ps1
```

## 更新前端

```powershell
cd D:\project\skill-forge-main\frontend
npm ci
npm run build
```

更新后刷新网页。不要在运行 Vite 开发服务时执行 `npm ci`，否则其占用的原生编译文件可能导致安装失败。

## 更新后端

等待所有业务任务完成，用管理员 PowerShell：

```powershell
cd D:\project\skill-forge-main
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\deploy\lan\update-backend.ps1
```

脚本读取线上配置、备份实际部署数据库、确认图片/Agent/创作任务空闲、停止 API、执行迁移并重启。API 重启后需重新填写图片密钥。备份仍需定期包括 `shared-data/` 与 `deployment.env`，不要只备份数据库。

如依赖有变化，先用 `stop.ps1 -Component Api` 停止，再在 `backend` 执行 `uv sync --locked`，最后运行更新脚本。停止服务请使用 `stop.ps1`，仅停止计划任务可能留下子进程。

运行日志在 `.lan-runtime/logs/`。IP 或端口修改 `settings.psd1` 后，需停止两个服务并以管理员运行 `install.ps1` 更新任务与防火墙。

当前为受信任局域网 HTTP 部署，传输不加密。无需将 8080 映射到互联网。

旧部署只能作为切换时的回退快照；新版上线后的新增数据不会自动同步回旧数据库，不要直接启动旧后端处理新数据。
