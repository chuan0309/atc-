# Gemini ATC

一個類似 BeyondATC 的 AI 塔台，給 MSFS 2020 / 2024 用：

- 🎙️ **Gemini 語音**：按住 PTT 講話 → Gemini 聽懂你的無線電呼叫、檢查覆誦 → 用 Gemini TTS 念回來（每個席位不同聲音，還有無線電濾波效果）
- 📋 **SimBrief**：自動抓你最新的 OFP（呼號、航路、SID/STAR、巡航高度、跑道）
- 🚐 **GSX Pro**：讀 GSX 各項地勤狀態；ATC 准許推出時自動幫你叫 GSX 推車
- ✈️ **飛行階段自動判斷**：Delivery → Ground → Tower → Departure → Center → Approach → Tower → Ground，換階段時 ATC 會主動呼叫你（交接頻率、下降許可等）

## 怎麼運作（簡單版）

```
你按 PTT 講話 ──► 錄音 WAV ──► Gemini（一次呼叫：語音轉文字 + 想 ATC 要回什麼）
                                   ▲ 附上：SimBrief 航班、飛機狀態、GSX 狀態、之前的對話
                                   ▼
             喇叭 ◄── 無線電濾波 ◄── Gemini TTS ◄── ATC 回覆文字
                                   ▼
                     准許推出？──► 寫 GSX 的 L:var 叫推車
```

模擬器資料是透過 SimConnect 讀的，GSX 是透過 `FSDT_GSX_*` 這些 L:var 溝通。

## 安裝（Windows）

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -e .[msfs]
copy config.example.toml config.toml
```

然後打開 `config.toml` 填：
1. `gemini.api_key`：去 https://aistudio.google.com/apikey 申請
2. `simbrief.username`：你的 SimBrief 帳號
3. `ptt.key`：按住講話的鍵（預設 Caps Lock），或填搖桿按鈕

## 使用

```bat
:: 先開 MSFS 進到駕駛艙、在 SimBrief 排好航班
python -m atc

:: 不想講話，用打字
python -m atc --text

:: 沒開模擬器，純測試（/next 推進假飛行階段）
python -m atc --mock --text --demo-plan
```

## 專案結構

| 檔案 | 做什麼 |
|---|---|
| `src/atc/simbrief.py` | 抓/解析 SimBrief OFP |
| `src/atc/sim/msfs.py` | SimConnect 讀飛機狀態、讀寫 L:var |
| `src/atc/sim/mock.py` | 假模擬器，測試用 |
| `src/atc/gsx.py` | GSX Pro 狀態 + 選單控制 |
| `src/atc/phases.py` | 判斷飛行階段、該跟哪個席位講話 |
| `src/atc/brain.py` | Gemini ATC 大腦（prompt、記憶指派高度/squawk/頻率） |
| `src/atc/voice/` | 錄音、PTT、Gemini TTS、無線電音效 |
| `src/atc/app.py` | 把上面全部串起來 |

## 目前限制 / 還沒驗證的地方（老實說）

- **我是在 Linux 上寫的，沒辦法實際開 MSFS 測**。SimBrief 解析、階段判斷、GSX 邏輯、Gemini 流程都有單元測試，但 SimConnect 和 GSX 真機要你在 Windows 上試。
- **GSX 選單檔位置**不同版本不一樣，找不到時會用「主選單第 5 項 = Request Pushback」的預設值；不對的話在 `config.toml` 的 `gsx.menu_file` 手動指定。
- 推出後 GSX 會再問方向等問題，目前要你自己在 GSX 選單點。
- **頻率**是 Gemini 依機場自己編的（還沒接真實頻率資料庫），預設不強制你調 COM1（`require_frequency = false`）。
- 沒有 AI 交通、沒有雷達隔離，ATC 不知道其他飛機。
- Gemini 模型名稱會更新，如果出錯就去 `config.toml` 換成最新的。

## 測試

```bash
pip install -e .[dev]
pytest
```
