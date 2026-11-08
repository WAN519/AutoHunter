# AutoHunter

帮你找实习、按岗位改简历、自动填申请表的工具。最后一步一定是你自己检查后点 Submit。
每个人的资料只存在自己电脑的 `me/` 文件夹里（不进 git），代码和 skill 大家共用。

> 找岗位、打分、改简历、写冷邮件：macOS / Windows 都能用。
> 自动填表、快捷键、每天自动运行：目前只支持 macOS。

## 第一次使用

1. 装好 [Claude Code](https://claude.com/claude-code) 和 [uv](https://docs.astral.sh/uv/)，clone 这个仓库。
2. 在仓库目录里打开 Claude Code，输入 **`/setup`**。它会一步步带你：
   - 回答几轮问题（学校、方向、什么时候开始、地点、签证），放进你的基础简历（**.docx**）
   - 打开**设置页**：联系方式、申请系统账号用的邮箱和密码（密码只存在 macOS 钥匙串里）、
     投实习 / 投 NG 的毕业时间、默认答案、快捷键、每天投几个、每天花费上限
   - （可选）连上你自己的 **Google 表格**，记录投过的岗位；装好**快捷键**；装好**每日自动运行**
3. 随时运行 `uv run main.py doctor`，可以看到哪些已经设好、哪些还缺，以及每项怎么补。

## 每天怎么用

| 想做什么 | 怎么做 |
|---|---|
| 看到一个想投的岗位 | 在 Chrome 的岗位页面按 **⌥ + 空格**（快捷键可以在设置页改）。它会先查重，再在后台改简历、填表，填好后发通知 |
| 发链接让我填 | 在 Claude Code 里说「帮我填这个 + 链接」 |
| 找新岗位并打分 | `/hunt` |
| 给某几个岗位改简历 | `/tailor 12 15` |
| 给没挂岗位的公司发冷邮件（比如问兼职 CPT） | `/outreach`，线索来自 `uv run main.py leads` |
| 告诉它简历该怎么改 | 直接说，例如「summary 太长了」，它会记住（`/style`） |
| 每天自动投 | 22:30 弹窗问明天投几个 → 23:00 搜岗位、打分、改简历 → 08:00 填好表，打开「今日清单」。**Workday 的岗位不提前填**（闲置会过期，已填内容会被清空）：简历先准备好，你准备检查时在清单上点「现在填」，1–2 分钟填好 |
| 重新打开今日清单 | `uv run main.py daily today` |

**填好以后**：AutoHunter 用的是一个**单独的 Chrome 窗口**（独立的配置，不碰你平时用的 Chrome）。
每个申请页右上角有面板，写着简历改了什么、哪些答案是 Claude 写的草稿、哪些项还需要你自己处理。
你检查完点 Submit，后台会自动截图，记进 `me/output/applied.csv`，同时同步到你的 Google 表格。

## 每个岗位会准备什么

一个岗位跑完 `/tailor`（快捷键和每日自动运行也会跑），`me/applications/<日期> <公司> - <职位>/` 里会有：

| 文件 | 内容 |
|---|---|
| `CV <你的名字> - <公司>.docx` / `.pdf` | 按这个 JD 改过的简历（一页，投 QA 岗等例外看你的偏好），上传用 PDF |
| `Cover Letter <你的名字> - <公司>.docx` / `.pdf` | **Cover letter**：JD 要求时写；申请表里有 cover letter 栏（上传框或文本框，必填或选填）时也会写，填表时自动上传或粘贴。只用你简历上的事实，按你认可的范例信的结构和语气写。只想必填时才写的话，在设置里改成 `"cover_letter": "required"` |
| `contacts.md` | **联系人**：Google 搜索链接，帮你在 LinkedIn 上找这家公司的招聘官、ML/工程负责人和你们学校的校友（链接要你自己点开，程序不登录也不抓取 LinkedIn），外加一条写好的 LinkedIn 好友申请留言（300 字符以内）和一封冷邮件草稿 |
| `notes.md` | 匹配度、简历每处修改的前后对比、你和 JD 的差距、投之前要确认的事（截止日期、开始时间、签证要求等） |
| `summary.json` | 简历改了什么、cover letter 写了哪几点，各一句话，会显示在填表面板、今日清单和 Google 表格里 |
| `jd.txt`、`plan.json`、`form.json` | 职位描述原文、改简历的计划、填表时用的答案（重新填一遍时会复用） |

另外：
- `me/output/contacts.csv`：每次 `hunt` 后，所有出现过的公司的联系人搜索链接汇总在这里
- `me/applications/outreach/`：`/outreach` 写的冷邮件（给没挂岗位的公司，例如问兼职 CPT）
- `me/output/leads.csv`：`uv run main.py leads` 从 Hacker News 招聘帖里整理出来的兼职 / 实习线索

所有邮件和留言都只是**草稿**，由你自己发，程序不会替你联系任何人。

## 支持哪些网站

| 能自动填 | 说明 |
|---|---|
| Greenhouse、Lever、Ashby | 一页表单，基本全自动 |
| Workday | 自动注册或登录账号（每家公司只注册一个），一步一步填到 Review 页 |
| 公司自己做的申请页（例如 Tesla） | 通用的多步填表，遇到不认识的项会停下来问你 |
| Eightfold / 公司招聘首页 | 自动找到背后真正的申请链接（比如 HP → Workday） |
| 拒绝自动化浏览器提交的网站（例如 Tesla） | 半自动：申请页在**你自己的 Chrome** 打开，点书签「AutoHunter 填表」填当前页 → 你点 Next → 再点书签 → … → 你提交。书签装一次：`uv run main.py apply kit <链接>` 会打开安装页 |

**不会自动操作的**：LinkedIn、Jobright、Handshake、Indeed、Glassdoor。这些网站的条款禁止用脚本访问，
或者账号太重要，不值得冒险。你在这些网站上看到岗位，点 Apply 跳到公司官网的页面后，再按快捷键。
iCIMS、Oracle、Taleo 这类需要另外注册账号的系统，暂时需要你自己投。

## 规则（写死在代码里）

- **永远不点 Submit**，不绕过验证码，**不替你签电子签名**。
- 必填的同意条款会替你勾上，面板上会用一句话说明你同意了什么。仲裁、背景调查这类条款会标 ⚠️。
- 简历上**不编造**任何技能、数字或经历。JD 需要、而你可能会但没写的技能，会先问你要不要加。
- 申请前会先读 JD 筛一遍：开始时间不对、经验超过上限、只招本科生、要求公民身份，都会先弹窗问你。

## 文件放在哪

```
me/                       你的私人文件夹（不进 git）
  config.json             求职设置 + 填表设置
  resume.docx             基础简历（越完整越好，改简历时再按岗位删减）
  profile.md              简历上没写的技能、不能改的内容、自我介绍素材
  resume_style.md         你的简历偏好（自动学习，你也可以直接改）
  experience.json         结构化的工作经历和学历（Workday 填表用）
  answers.json            常见问题的默认答案 + 你回答过的问题
  applications/<岗位>/    这个岗位的定制简历、cover letter、联系人（contacts.md）、改动说明（见上面「每个岗位会准备什么」）
  applications/outreach/  冷邮件草稿
  output/                 tracker.csv（所有岗位）、applied.csv（投过的）、contacts.csv（联系人搜索链接）、
                          leads.csv（兼职 / 实习线索）、today.html（今日清单）
```

## 常用命令

```bash
uv run main.py doctor            # 体检：哪些设好了，哪些还缺
uv run main.py hunt              # 搜岗位（Greenhouse / Lever / Ashby / Workday / SmartRecruiters / HN / Simplify）
uv run main.py settings          # 打开设置页
uv run main.py daily status      # 每日运行的状态；daily uninstall 关掉
uv run main.py sheets sync       # 手动同步 Google 表格；sheets pull 把表格里的改动拉回来
```

添加公司：把招聘页的 token 加进 `companies.json`（格式见文件开头的说明），然后提 PR。
