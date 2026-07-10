# waagent 使用教學

從零開始到產出第一份 WA 評估報告。

---

## 1. 安裝

### 方式 A：開發機（有網路）

```powershell
git clone https://github.com/kaikaichumi/Awagent.git
cd Awagent
pip install -e .
python -m copilot download-runtime    # 下載 Copilot agent runtime（約 130MB）
```

### 方式 B：公司電腦（離線 ZIP）

解壓 `waagent-bundle.zip` 後：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

詳見包內 `INSTALL.md`（含 proxy、SSO、疑難排解）。

---

## 2. 第一次啟動（10 分鐘）

> 若出現 `'waagent' 不是內部或外部命令`：改用 `python -m waagent`（完全等價），
> 或參考 INSTALL.md 疑難排解把 Python Scripts 目錄加入 PATH。

### 步驟 1：健康檢查

```powershell
waagent doctor
```

七關逐項檢查。**哪一關 FAIL 就只處理那一關**：

| 關卡 | FAIL 時怎麼辦 |
|---|---|
| 1 設定檔 | WARN 可忽略（用預設值）；要改設定才需要建 config.toml |
| 2 網路 | 填 config 的 proxy / ca_bundle（公司網路才需要） |
| 3 Copilot | `pip install github-copilot-sdk` + runtime；或登入 GitHub（見下） |
| 4 AWS | `aws configure sso`（公司）或 `aws configure`（個人帳號） |
| 5 WA Tool | 同上，另需 IAM 有 wellarchitected 讀取權限 |
| 6 模板 | INFO 可忽略（用內建模板） |
| 7 MCP/skills | INFO 可忽略（選配功能） |

### 步驟 2：GitHub Copilot 登入（擇一）

- 電腦已登入過 `gh auth login` 或 VS Code Copilot → 什麼都不用做
- 沒有的話：第一次 `waagent chat` 會跳裝置授權，照畫面到 github.com 輸入代碼

### 步驟 3：開聊

```powershell
waagent
```

看到 `coder>` 提示符就成功了。先隨便聊一句確認通了：

```
coder> 你好，介紹一下你自己有哪些工具
```

啟動時會顯示一行 `auto 路由啟用：地板 claude-sonnet-x / 升級 xxx`——
這代表自動選模型已生效（雜活用便宜模型、難題自動升級）。

---

## 3. 基本操作

三種模式，用 `/mode` 切換（或啟動時 `waagent chat -m <模式>`）：

| 模式 | 用途 | 工具 |
|---|---|---|
| `coder`（預設） | 日常寫程式，像 Claude Code | 編輯檔案、跑命令 |
| `aws-debug` | AWS 除錯 | coder 全部 + 唯讀 AWS 查詢 |
| `wa-review` | WA 評估 | 掃描/報告/WA Tool（停用 shell，較安全） |

常用指令（隨時 `/help` 查）：

```
/mode wa-review     切換模式
/image 架構圖.png   附圖給 AI 看
/scan               執行 AWS 掃描
/report             產生報告
/diff               比較最近兩次掃描
/usage              看 token/額度用量
/model              看可用模型；/model gpt-5 釘選；/model auto 恢復自動
/memory             看長期記憶
/resume             接續上次的對話
/clear              重開 session
/exit               離開
```

---

## 4. 場景教學

### 場景 A：日常寫程式（coder 模式）

跟 Claude Code 一樣用，在專案目錄下啟動 `waagent`：

```
coder> 幫我看看 src/main.py 為什麼跑起來會 timeout，修好它
```

它會自己讀檔、改檔、跑命令驗證。改檔和跑命令前會問你允不允許。

### 場景 B：AWS 除錯（aws-debug 模式）

```powershell
waagent chat -m aws-debug
```

```
aws-debug> prod 的 API 從昨天下午開始一直 500，幫我查原因
```

agent 的標準路數：查 CloudWatch Logs 抓錯誤 → 查 CloudTrail「昨天下午誰改了什麼」
→ describe 資源現況 → 給出結論和修法。你也可以指定：

```
aws-debug> 查 /aws/lambda/order-api 最近 2 小時的錯誤日誌
aws-debug> 昨天有誰動過 security group？
aws-debug> 看一下 prod-db 這三小時的 CPU
```

### 場景 C：WA 評估（完整流程）

```powershell
waagent chat -m wa-review
```

```
wa-review> /scan                          ← 掃描帳號（唯讀，幾分鐘）
wa-review> /image .\我們的架構圖.png
wa-review> 請對照這張架構圖與掃描結果，做六大支柱評估，
           特別注意圖上有但掃描沒看到的元件
wa-review> /report                        ← 產出 report.md + report.html
```

打開 `wa-report-*.html` 就是含雷達圖/風險分布的視覺化報告。

想同步到 AWS WA Tool（正式留紀錄）：

```
wa-review> 列出現有的 workload
wa-review> 把這次評估的安全性支柱答案更新到 workload xxx
           （每筆寫入都會在終端顯示內容要你按 y 確認）
wa-review> 建立一個 milestone 叫「2026Q3 初評」
```

**一個月後複評**：修完問題再 `/scan` 一次，然後：

```
wa-review> /diff     ← 自動比較：修好了哪些、新增了哪些
```

或不進對話直接 `waagent diff` 看表格。

---

## 5. 報告模板（讓報告長成你要的樣子）

1. 建一個資料夾，例如 `C:\wa-templates`
2. config.toml 填 `[wa] templates_dir = "C:\\wa-templates"`
3. 資料夾裡放：

| 檔案 | 作用 |
|---|---|
| `*.rules.md` | 寫作規則，例如「報告用敬語」「每個風險要附影響評估」「結論不超過 300 字」 |
| `report.md.j2` | 覆蓋內建 Markdown 模板（選配） |
| `report.html.j2` | 覆蓋內建 HTML 模板（選配） |

規則檔範例（`style.rules.md`）：

```markdown
# 報告寫作規則
- 對象是不懂技術的主管，避免術語，每個風險用一句話講清楚商業影響
- 修正建議要標注預估工時（S/M/L）
- 執行摘要最後要有一行「本月最優先處理事項」
```

**每次評估都會全量重讀這個資料夾**——隨時改規則，下次 `/report` 就生效。
改了模板想重出報告不用重跑 AI：`waagent report`。

---

## 6. 模型與額度

- 預設 `model = "auto"`：**waagent 本地規則**選模型（不是 Copilot 的 auto）。
  查資料、掃描、小修改 → Sonnet 級地板；設計/架構/報告/附圖/長需求 → 自動升級。
  每次切換會顯示 `[auto] 本回合 xxx（原因）`。
- 額度焦慮時：`/usage` 看各模型用了幾回合；config 設 `max_ai_credits` 加上限。
- 省額度心法：架構討論、報告撰寫讓它自動升級沒關係——真正吃額度的是
  「大量來回的雜活」，而那些都在地板模型上跑。

## 7. 記憶

- agent 覺得重要的事會主動 `memory_save`（也可以叫它記：「記住：我們的
  web-sg 開 SSH 是跳板機，已核可」）
- 每個新 session 自動載入；`/memory` 或 `waagent memory` 查看
- 檔案在 `~\.waagent\memory.md`，可直接手動編輯/刪除
- 對話中斷想接續：`/resume` 列出歷史 session，`/resume <id>` 接上

## 8. FAQ

**Q: 掃描會不會動到我的 AWS 資源？**
不會。collectors 層強制只允許 describe/list/get 開頭的 API；唯一的寫入
（WA Tool 答案/milestone）每筆都要你在終端按 y。

**Q: SSO token 過期了？**
`aws sso login --profile <名稱>` 重新登入即可，waagent 遇到會直接提示這行指令。

**Q: 對話太長會爆掉嗎？**
不會。context 用到 80% 會自動背景壓縮（顯示「context 壓縮中…」），
掃描結果都在磁碟上，`/clear` 重開也能一句話撈回狀態。

**Q: 中文變亂碼？**
用 Windows Terminal（或 `chcp 65001`）。程式本身輸出 UTF-8 不會崩潰。

**Q: 想看掃描的原始資料？**
`~\.waagent\runs\<時間>\` 下有 raw/（完整 API 回應）、findings.json、digest.json。
