# 梦幻西游 · 牧场助手

基于《牧场饲养攻略》文档构建的牧场养殖管理 Web 工具，帮助玩家追踪每只动物的养殖状态，并给出每日喂养建议。

---

## 功能特性

- **动物列表**：平铺展示所有正在养殖的动物，包含当前天数、阶段、饱食度、今日产出
- **喂养建议**：根据养殖计划表自动计算今天是否需要喂养及喂养数量，一键记录喂养
- **今日摘要**：顶部横条汇总今日待喂动物数量及今日产出情况
- **筛选功能**：支持按动物种类、喂养状态进行筛选
- **新增养育**：选择物种、填写开始日期即可新增，昵称选填（默认为「物种名+日期」）
- **售出管理**：售出动物后逻辑删除，历史记录保留在数据库
- **动态物种**：物种数据从 `牧场饲养攻略.md` 解析写入数据库，新增物种只需编辑文档

---

## 支持动物

| 物种 | 幼年期 | 成年期 | 额外寿命 | 总天数 |
|------|--------|--------|----------|--------|
| 🐼 熊猫 | 5天 | 10天 | 3天 | 18天 |
| 🦎 娃娃鱼 | 3天 | 8天 | 3天 | 13天 |
| 🐊 鳄鱼 | 3天 | 8天 | 3天 | 13天 |
| 🐆 豹子 | 3天 | 8天 | 3天 | 13天 |
| 🦜 金刚鹦鹉 | 4天 | 8天 | 3天 | 14天 |

---

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | Python 3.12 + FastAPI |
| 数据库 | SQLite（aiosqlite 异步驱动） |
| 前端 | HTML + Tailwind CSS + Alpine.js |
| 部署 | Docker + Docker Compose |

---

## 项目结构

```
.
├── main.py                   # FastAPI 应用入口
├── requirements.txt          # Python 依赖
├── Dockerfile
├── docker-compose.yml
├── 牧场饲养攻略.md            # 物种数据源（首次启动时解析写入数据库）
└── app/
    ├── api.py                # REST API 路由
    ├── database.py           # 数据库初始化、迁移、Seed
    ├── seed_parser.py        # Markdown 解析器
    └── templates/
        └── index.html        # 单页前端
```

### 数据库表结构

```
species             物种基本信息（饲养计划基表）
feeding_schedule    每日喂养计划（饲养计划基表）
animals             养育中的动物（售出时逻辑删除）
feed_logs           每日喂养记录
```

---

## 快速开始

### 本地运行

```bash
pip install -r requirements.txt
DB_PATH=./data/farm.db uvicorn main:app --reload
# 访问 http://localhost:8000
```

### Docker 部署

```bash
docker compose up -d --build
# 访问 http://localhost:8080
```

---

## 云服务器部署（不开放外网端口）

服务绑定在服务器本地 `127.0.0.1:8000`，通过 **SSH 隧道**在本地访问，无需开放任何公网端口。

### 服务器首次部署

```bash
# 1. 安装 Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# 2. 拉取代码
git clone https://github.com/<用户名>/<仓库名>.git /opt/farm
cd /opt/farm

# 3. 启动服务
docker compose up -d --build
```

### 本地建立 SSH 隧道访问

```bash
ssh -L 8080:localhost:8000 -N user@your-server-ip
```

浏览器访问 `http://localhost:8080` 即可。

**推荐：将隧道写入 SSH config（`~/.ssh/config`）**

```
Host farm
    HostName your-server-ip
    User your-user
    LocalForward 8080 localhost:8000
```

之后只需 `ssh farm`，隧道自动建立。

### 更新部署

```bash
# 本地推送代码后，在服务器执行：
cd /opt/farm && git pull && docker compose up -d --build

# 或在本地一步完成：
ssh user@your-server-ip "cd /opt/farm && git pull && docker compose up -d --build"
```

---

## 扩展新物种

1. 在 `牧场饲养攻略.md` 中按现有格式新增一节（`### N、物种名`）
2. 在 `app/seed_parser.py` 的 `_EMOJI_MAP` 中添加对应 emoji
3. 清空数据库中的 `species` 和 `feeding_schedule` 表，或全新部署
4. 重启服务，新物种自动出现在「养育」弹窗的种类选择中
