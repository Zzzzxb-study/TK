# Linux 服务器部署

已提供 Docker Compose + PostgreSQL + Caddy HTTPS 配置。当前仅在 Windows 本机验证；尚未在真实服务器部署。需要 Docker Engine / Compose、域名解析到服务器，并允许 80 / 443 入站。数据库和应用端口不映射到公网。

## 启动

1. 将应用目录复制到服务器，排除 .venv、data、.env、test-results；不要复制本地初始密码。
2. cp .env.example .env，设置真实 DOMAIN、强随机 DJANGO_SECRET_KEY 和 DB_PASSWORD。域名仅填主机名，不含 https://。
3. docker compose up -d --build
4. docker compose exec app python manage.py init_admin
5. 按提示输入初始管理员密码，登录域名并立即改密。
6. docker compose exec app python manage.py check --deploy

生产配置要求环境变量和 PostgreSQL；不自动使用开发密钥或 SQLite。生产 HTTP 强制跳转 HTTPS，Cookie 仅通过 HTTPS 发送。Caddy 只公开静态资源目录，不能将 /data 映射成公共下载目录。私有存储与数据库使用独立命名卷，更新容器保留数据，不要使用 docker compose down -v。

## 导入现有资料

将现有十个险种目录放在服务器 /srv/insurance-source，在 app.volumes 临时增加：
  - /srv/insurance-source:/source:ro

重新创建 app 后运行：
  docker compose exec app python manage.py import_documents /source --apply --normalize-pdf-names
  docker compose exec app python manage.py verify_storage

查看 /data/import-report.json 中的异常列表。导入完成后可移除只读源目录挂载。管理员初始密码必须独立设置，不能把本机管理员密码文件放进镜像。

## 备份与恢复

备份需要数据库和 /data/files 同一批次，不能只备份其中一个。最简单的一致性策略是在维护时间暂停 app 写入：

  mkdir -p server-backups
  docker compose stop app
  docker compose exec -T db pg_dump -U clauses -d clauses -Fc > server-backups/clauses.dump
  docker compose run --rm --no-deps -T --entrypoint tar app -C /data -czf - files > server-backups/files.tar.gz
  docker compose start app

这些重定向命令用于 Linux shell。操作前确认磁盘空间；任一步失败都不要覆盖上一份已验证备份。另行妥善保存 .env 的部署密钥，文件权限设为 600。备份应复制到服务器之外的受控位置。

恢复到空的测试环境：先运行迁移建立数据库，再停 app；用 pg_restore --clean --if-exists --no-owner 恢复数据库，解压文件备份至 /data/files，确认应用 UID 10001 可读写，然后启动 app。运行 verify_storage 并实际验证登录、下载和回收站恢复。演练成功后再将同一流程用于正式恢复。本轮未在服务器执行备份恢复演练。

## 运维

- 命名卷 documents 保存条款，database 保存 PostgreSQL。
- 按业务需求安排备份和 Django clearsessions 会话清理。
- 第一版为单应用实例；多实例扩容前需改共享文件存储，并评估并发及登录限流。
- 默认上传 20 MiB，入口限制 22 MB；调整时同步修改应用与代理配置。
- Waitress 仅在不公开端口的容器网络内信任 Caddy 转发的来源地址与 HTTPS 协议；不要将 app 的 8000 端口暴露到公网。多级代理需重新确认可信代理链。
- Docker / PostgreSQL / HTTPS 部署待实际服务器验证，不能把本机通过视为生产验证完成。


代理配置依据：[Waitress 代理头说明](https://docs.pylonsproject.org/projects/waitress/en/latest/arguments.html)、[Caddy 反向代理说明](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)。
