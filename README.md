# QQ 群每日/每周摘要（NapCat + OneBot + SQLite）

把 USTC飞跃群2027（QQ 群 1035480173）的消息采集到本地数据库，按固定格式压缩成"要点"档案，定时推送到 Telegram。

> ⚠️ **隐私提示**：摘要要点保留了**消息来源（群名片/昵称）**，方便回溯原消息。
> 群名片常含真实姓名、年级、专业与去向，**公开分享前请先取得群友理解**。
> 若需对外发布又不想暴露身份，运行 `collector/qq_redact.py --redact-names`
> 生成代号版（群友01/群友02…）。

## 结构

```
collector/            # 采集与处理脚本
  qq_collector.py     # OneBot 事件上报 → SQLite（只收白名单群）
  qq_digest.py        # 取最近 N 小时消息 → 生成给模型用的原始材料
  qq_archive.py       # 查阅摘要档案（--list / --grep / --today）
  qq_alert.py         # 高价值关键词即时提醒（无命中时静默）
  qq_prune.py         # 90 天以上原始消息 → gzip 归档
  qq_boot.py          # 一次性拉起 NapCat + 采集器（可开机自启）
  napcat_ctl.py       # NapCat 启停/状态
digests/              # 摘要档案（Markdown），按 年/月 分层
  INDEX.md            # 一行一期总索引
```


## 术语小抄（对圈外人友好）

留学/科研申请圈的行话（DDL、套磁、组招、全奖、强 prof、暑研、fellowship、结题报告、VISP…），
外行看不懂，所以：

- `collector/glossary.json` 维护「术语 → 一句大白话」，字段 `name` / `pat`（正则）/ `say`
- **即时提醒**：命中消息里出现的术语时，自动附上解释（最多 3 条）
- **周报**：写完 md 后跑 `python qq_annotate.py <文件>`，生成**课本式脚注**——正文标半角方括号角标（`[1]`、`[2]`），正文下方列「📖 注释」：
  `NUS CDE[1]/ISEM[2] 李在乐组招[3] …` → `[1] NUS CDE：新加坡国立大学 设计与工程学院`
  按正文出现顺序编号、每个词只标一次、重复跑内容不变（幂等）

想加词就改 `glossary.json`，两个出口同时生效，不用动代码。

## 工作流

```
QQ 客户端 ──NapCat(注入)──> OneBot HTTP(127.0.0.1:3000)
                                   │
                                   └─ 事件上报(127.0.0.1:5700) ──> SQLite
                                                                   │
                        cron：每周一 08:00 ──> qq_digest.py ──> 摘要 Markdown + Telegram
                        cron：每 20 分钟   ──> qq_alert.py  ──> 命中关键词才推送
                        cron：每月 1 日    ──> qq_prune.py  ──> 90 天前数据归档
```

## 摘要格式（每期 ≤14 行）

```
# 2026-10-19 ~ 10-25 · NUS 招博 DDL1.15、复旦 AI3 招人

- 180 条 / 42 人 · 高峰 16–18 点
- 【招生】NUS CDE 李在乐组招 2027 Fall 全奖博士，DDL 1.15
- 【截止】国合部资助 9 月提交仍待审核
- 【经验】NUS 理学院强 com；ISEM/CDE 强 prof 靠老板提名
- 【文件】PhD_Postdoc_Openings_Baier_lab.pdf
- 噪音：表情/闲聊 40 条，重复转发已合并 6 条

> 标准：招生/DDL > 流程通知 > 经验帖 > 求问 > 闲聊
```

## 配置（环境变量）

所有路径与群信息集中在 `collector/paths.py`，不再写死某台机器的绝对路径：

| 环境变量 | 作用 | 默认值 |
|---|---|---|
| `QQ_WORKSPACE` | 工作区根目录（数据库、摘要、归档都在其下） | `~/qq-workspace` |
| `NAPCAT_HOME` | NapCat 安装目录 | `~/napcat/shell` |
| `QQ_GROUP_ID` | 采集的目标群号（也可写在 `napcat_credentials.json` 的 `group_id`） | 无，必须提供 |
| `QQ_GROUP_NAME` | 摘要标题里显示的群名 | `某高校飞跃群` |

## 自建步骤（操作不熟练的话建议全部交给 agent 处理，这个项目本身也是 agent work）

1. 安装 QQ NT 客户端，下载 [NapCat](https://github.com/NapNeko/NapCatQQ/releases) 的 `NapCat.Shell.zip`，解压。
2. 把 `loadNapCat.js` 复制到 QQ 的 `resources/app/` 目录（部分版本需要管理员权限）。
3. 首次启动用二维码登录；之后用 `-q <QQ号>` 快速登录。
4. 修改 `config/onebot11_<QQ号>.json`，开启：
   - `httpServers`：`127.0.0.1:3000`（供脚本调用 API，**必须带 token**）
   - `httpClients`：`http://127.0.0.1:5700`（把事件推给采集器）
5. 设置 `QQ_GROUP_ID` 与 `QQ_WORKSPACE`，启动采集器。
6. 用 cron / 计划任务按上面的节奏跑 `qq_digest.py`、`qq_alert.py`、`qq_prune.py`。

> **Windows 注意**：NapCat 必须用「独立控制台」启动（`CREATE_NEW_CONSOLE`），
> 用 `DETACHED_PROCESS` 会让它的 Worker 进程在登录时崩溃；
> 且从其他进程用 Popen 拉起会被父进程回收，建议交给「任务计划程序」托管。

## 安全约定

- 所有服务只监听 `127.0.0.1`，不暴露公网。
- 采集器**只入库白名单群**，群号从配置读取，代码里不含真实群号。
- 只读：代码里没有任何发送消息的调用。
- 凭据、数据库、日志一律 `.gitignore`，不进仓库。
- 账号有被平台风控的可能，请自行评估。

## 许可

个人自用项目，代码可自由参考。摘要内容版权归原群成员。
