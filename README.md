# TK · 保险条款库

一个支持工号登录、权限管理和服务器私有文件存储的保险条款管理应用。

**本仓库仅包含程序源码、测试和部署配置，不包含任何原始条款、费率文件、运行数据库或真实账号密码。**

## 功能

- 目录：产品类别（可含子类别）→ 产品 → 主险 / 附加险 → 条款、费率。
- 管理员新增、编辑、停用及启用产品类别；改名保留原目录来源映射。
- 上传 DOC、DOCX、PDF，单个文件最大 20 MiB；文件结构及大小校验。
- 上传、下载、删除独立授权；默认员工仅查看目录。
- 管理员创建工号、重置密码和停用账号；首次登录必须改密，不开放注册。
- 文件下载经过服务端鉴权，没有公开的原文件 URL。
- 回收站删除与恢复、操作记录、关键词检索。
- 批量导入、重复导入不重复建记录、相同内容去重存储和 SHA-256 核验。

类别停用后，普通工号无法浏览或下载其下资料，也不能新增上传；管理员保留历史访问。停用不删除文件，下属类别随上级暂停使用，重新启用上级不会改变子类别自身的停用状态。

## 快速开始（Windows）

需要 Python 3.13，首次安装需要联网下载依赖。

```powershell
git clone https://github.com/Zzzzxb-study/TK.git
cd TK
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py init_admin
.\.venv\Scripts\python.exe run_local.py
```

访问 http://127.0.0.1:8000 。初始管理员账号默认是 admin，密码在初始化时交互设置，至少 12 位。首次登录必须修改密码。初始化发现已有管理员时不会重置密码。

以后可运行 start.ps1 或 run_local.py 启动。本机默认使用 SQLite，仅监听本机地址。服务器部署采用 PostgreSQL、持久磁盘和 HTTPS，见 [部署说明](deploy/README.md)。

## 使用流程

1. 管理员登录并修改初始密码。
2. 在“类别管理”维护产品类别、上下级关系和启停状态。
3. 在“工号管理”创建员工，分别分配上传、下载、删除权限。
4. 上传资料时选择类别、已有产品（或填写新产品）、主险/附加险、条款/费率。
5. 按产品目录查找资料；删除进入回收站，管理员可恢复。
6. 管理员可在详情中核对名称、主附险、资料类型和版本。

## 导入自己的资料

原始文件应放在仓库之外，例如 D:\\insurance-source。导入器识别保证保险、财产保险、船舶保险、工程保险、货运保险、健康保险、其他保险、特殊保险、意外保险和责任保险十个顶层目录；财产保险支持家庭财产保险、企业财产保险子类别。

```powershell
.\.venv\Scripts\python.exe manage.py import_documents D:\insurance-source --report data/preflight.json
.\.venv\Scripts\python.exe manage.py import_documents D:\insurance-source --apply --normalize-pdf-names
.\.venv\Scripts\python.exe manage.py verify_storage
```

默认预检查，--apply 才写入。源文件不做修改。--normalize-pdf-names 仅修正真实 PDF 文件的错误下载后缀，保留来源路径和原始内容；其他格式异常会列入报告。

相同内容可共用一份存储，保留各产品关联。原路径内容变化会报告冲突，不自动覆盖版本。重复导入不恢复回收站记录。数字文件名及无法判断的资料保留待核对标记，不自动猜测名称。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py verify_storage
```

测试使用临时数据库、临时文件和合成样本，不依赖实际条款。已有 Windows 本地验证；正式 PostgreSQL、容器、HTTPS 和备份恢复仍应在目标服务器验收。

## 目录

```text
config/       应用配置
library/      账户、权限、目录、文件和导入逻辑
templates/    中文页面
static/       页面样式
deploy/       HTTPS 和服务器部署说明
data/         运行时自动生成，禁止提交
```

## 数据与运行边界

- 本机数据：data/library.sqlite3、data/files 和 data/.secret_key。服务器原文件保存在 /data/files 持久卷。
- .env.example 只提供占位配置；真实 .env、密钥、密码和数据库均不得提交。
- 上传文件只作为附件下载，不提供在线正文预览或恶意软件扫描。
- 版本和主附险归属属于整理信息，不代表对条款效力、备案状态或适用范围作业务判断。
- 回收站为逻辑删除；没有自动永久清理。
- 下载日志表示授权并开始传输，不证明客户端保存完成。
- 数据库和文件必须同批次备份；升级容器不要删除数据卷。
- 仓库忽略规则额外排除 Word、PDF、数据库及常见归档文件，避免误提交业务资料。
