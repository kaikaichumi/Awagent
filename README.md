# waagent

用**公司 GitHub Copilot 企業版額度**驅動的 AWS Well-Architected AI agent，
同時也是一個類 Claude Code 的日常終端 coding agent。

> 新手請直接看 **[TUTORIAL.md](TUTORIAL.md)** —— 從安裝到產出第一份報告的完整教學。

## 功能

- **`coder` 模式（預設）**：Copilot SDK agent 全功能——多輪對話、編輯檔案、執行命令。
- **`aws-debug` 模式**：coding 工具 + 唯讀 AWS 除錯工具——CloudWatch Logs Insights
  查日誌、CloudTrail 查「誰改了什麼」、metrics 查指標、`aws_describe` 任意唯讀查詢。
- **`wa-review` 模式**：掃描 AWS 帳號（唯讀）、對照 WA 六大支柱評估、產生
  Markdown + 視覺化 HTML 報告（單檔離線可開）、可寫回 AWS Well-Architected Tool。
- **auto 模型路由（本地，非 Copilot auto）**：`model = "auto"` 時由 waagent 自己的
  規則引擎每回合選模型——雜活用地板模型（預設 Sonnet 級，絕不更低）、深度任務
  （設計/架構/報告/附圖/長需求）自動升級最強模型；每回合顯示選了誰與原因，
  `/model <id>` 隨時釘選、規則與地板全在 config 自訂。
- **context 超限自動處理**：SDK infinite sessions——context 用到 80% 背景自動壓縮、
  95% 阻塞等壓縮完成；每回合顯示 context 使用率，`/usage` 看累計 token/credits。
- **記憶**：SDK 原生對話記憶 + `~\.waagent\memory.md` 長期記憶（agent 用
  `memory_save` 寫入、每個 session 自動載入、可手動編輯）。
- **session 接續**：`/resume` 列出歷史 session、`waagent chat --resume <id>` 接續。
- **修正驗證**：`waagent diff` / `/diff` 比較兩次掃描——已修復 / 新增 / 未變。
- **額度保護**：`max_ai_credits` 可設單 session credits 上限；工具輸出一律截斷防灌爆 context。
- **圖片輸入**：`/image 架構圖.png` 讓 AI 對照架構圖與掃描結果。
- **模板規則資料夾**：報告寫作規則與 Jinja2 模板放在資料夾內，隨時增修，每次評估全量重讀。
- **公司 proxy 友善**：proxy / 自訂 CA 一處設定，涵蓋 Copilot 與 AWS 全部連線。
- **MCP servers 接入**：`config.toml` 的 `[mcp.<name>]` 子表直接對應 SDK 的 MCP server 設定
  （command/stdio 或 url/http 皆可），啟動 session 時自動接上。
- **skills 目錄**：`copilot.skill_directories` 指定額外 skill 資料夾，自動啟用 SDK 的 skills 功能。

## 安裝

```powershell
pip install -e .
pip install github-copilot-sdk
python -m copilot download-runtime   # 下載 Copilot agent runtime
```

認證（擇一）：
- 已用 `gh auth login` 或 Copilot CLI 登入過 → 直接可用
- 設 `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` 環境變數

> 企業管理員需在 GitHub org policy 啟用 Copilot CLI/SDK 與所需模型。

## 設定

複製 `config.example.toml` 到 `%LOCALAPPDATA%\waagent\config.toml`（或專案根目錄 `.waagent.toml`），
填入 proxy、CA bundle、AWS profile/region、模板資料夾等。全域設定的實際路徑依作業系統而異，
以 `waagent doctor` 第 1 關顯示的路徑為準。

MCP servers 與 skills 皆為選配：`[mcp.<name>]` 子表原樣傳給 Copilot SDK（至少要有 `command`
或 `url` 其一，缺兩者的項目會被忽略），`[copilot] skill_directories` 則指定額外 skill 資料夾。
兩者都留空即維持原本行為。設定是否生效可用 `waagent doctor` 第 7 節確認。

## 使用

```powershell
waagent doctor        # 逐項檢查：設定 → proxy → Copilot → AWS → WA Tool → 模板
waagent               # 進入 chat REPL（coder 模式）
waagent chat -m wa-review   # 直接進 WA 評估模式
waagent chat -m aws-debug   # AWS 除錯模式
waagent chat --resume <id>  # 接續上次 session
waagent scan          # 純掃描（不用 LLM，可排程）
waagent diff          # 比較最近兩次掃描（修正驗證）
waagent report        # 用既有 narrative 重渲染報告（改模板不必重跑 LLM）
waagent runs          # 歷史掃描清單
waagent memory        # 顯示長期記憶
```

REPL 內指令：`/mode`、`/image <路徑>`、`/scan`、`/report`、`/diff`、`/resume`、
`/usage`、`/model`、`/memory`、`/clear`、`/help`、`/exit`。

### 典型 AWS 除錯流程

```
waagent chat -m aws-debug
> prod 的 API 從昨晚開始一直 500，幫我查
  （agent 會：logs insights 抓錯誤 → cloudtrail 查昨晚誰改了什麼
   → describe 現在的資源狀態 → 對照原始碼給出修法）
```

### 典型 WA 評估流程

```
waagent chat -m wa-review
> /scan                      # 掃描帳號（唯讀 API）
> /image .\架構圖.png
> 請對照這張架構圖與掃描結果，評估六大支柱
> /report                    # 依模板規則產出 md + html 報告
> 把安全性支柱的答案同步到 WA Tool workload   # 寫入前會在終端要求確認
```

## 掃描的 IAM 權限

- 掃描：`ReadOnlyAccess`（或收斂的自訂唯讀 policy）
- WA Tool 寫回：`wellarchitected:CreateWorkload / UpdateAnswer / CreateMilestone / GetLensReviewReport`

## 開發

```powershell
pip install -e .[dev]
pytest
```

架構重點見 `.waagent` 計畫文件：raw → findings → digest 三層資料流
（LLM 只讀 digest，token 開銷可控）；所有 Copilot SDK 呼叫收斂在
`chat/session.py` 與 `agents/registry.py`。
