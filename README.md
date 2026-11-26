# Gemini ATC

一個類似 BeyondATC 的 AI 塔台，給 MSFS 2020 / 2024 用：

- 🎙️ **Gemini 語音**：按住 PTT 講話 → Gemini 聽懂你的無線電呼叫、檢查覆誦 → 用 Gemini TTS 念回來（每個席位不同聲音，還有無線電濾波效果）
- 📋 **SimBrief**：自動抓你最新的 OFP（呼號、航路、SID/STAR、巡航高度、跑道）
- 🚐 **GSX Pro**：讀 GSX 各項地勤狀態；ATC 准許推出時自動幫你叫 GSX 推車
- 🛫 **FSLTL AI 交通**：用 FSLTL 的模型生出 AI 飛機，塔台會指揮它們 line up、起飛、落地、重飛，你在無線電裡聽得到；你要起飛/落地時 ATC 會照跑道狀況幫你排序（hold short、number 2、go around）
- 🗓️ **真實班表**：AI 飛機用真實航班（真的呼號、航空公司、機型、起降時間），由我們的引擎飛，所以 ATC 能真的指揮它們；你周圍空域的真實航班也會出現在畫面上
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

## AI 交通（FSLTL）怎麼運作

1. **找模型**：自動從 MSFS 的 `UserCfg.opt` 找 Community 資料夾，讀 `fsltl-traffic-base` 裡的 `*.vmr` 對照表（航空公司＋機型 → 模型名稱）；沒有 vmr 就直接掃 `aircraft.cfg`。
2. **找跑道**：用 SimBrief 排的起降跑道，跑道座標從 OurAirports 公開資料抓（第一次會下載，存在 `~/.gemini-atc/`）。
3. **生飛機**：用 SimConnect `AICreateNonATCAircraft` 生 FSLTL 模型，再把 MSFS 自己的 AI 控制凍結，位置由我們每 0.2 秒設定。
4. **指揮**：
   - 出發機：跑道頭旁等待 → line up and wait → cleared for takeoff → 爬升 → contact departure → 消失
   - 到場機：10 海里五邊出現 → cleared to land → 落地滾行 → contact ground → 消失
   - 跑道一次只給一架用（包括你）。你在 6 海里五邊內，或 ATC 已經給你起飛/落地許可，AI 都會讓你。跑道被擋住時，AI 到場機在 1 海里會被叫重飛。
5. **跟你排序**：每次你呼叫 ATC，Gemini 都會拿到目前跑道/五邊上有誰，照這個決定要不要讓你等。

AI 交通只在你目前的機場出現：出發階段在起飛機場，進場以後在目的地機場，巡航時不會有。找不到 FSLTL 模型時，AI 飛機不會出現在畫面上，可是無線電跟排序還是會照樣運作（等於「看不到的交通」）。

## 真實班表

AI 飛機不是隨機亂生的，而是照真實班表：

| 情況 | AI 什麼時候出現 |
|---|---|
| 出發機 | 表定起飛時間 + 8 分鐘（假裝滑行），出現在跑道頭等待 |
| 到場機 | 表定落地前 4 分鐘，出現在 10 海里五邊 |
| 空中 | 照起降時間算出「現在應該飛到大圓航線的哪裡」，離你 40 海里內就出現（只顯示，不指揮） |

班表來源（`config.toml` 的 `[schedule]`）：
1. **AeroDataBox**：去 RapidAPI 申請 AeroDataBox 的 key（有免費方案）。程式只抓你出發/目的地兩個機場，每小時最多各抓一次，有快取，很省額度。
2. **自己的 CSV**：照 `schedule.example.csv` 的格式填，每天重複。
3. 都沒有的話，就退回隨機產生的航班。

FSLTL 模型會照「航空公司＋機型」去配，例如 EVA 的 B77W 就會用長榮 777 的塗裝。

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
| `src/atc/traffic/fsltl.py` | 找 FSLTL 模型（vmr 對照表 / aircraft.cfg） |
| `src/atc/traffic/runways.py` | 跑道資料（OurAirports） |
| `src/atc/traffic/schedule.py` | 真實班表（AeroDataBox / CSV） |
| `src/atc/traffic/enroute.py` | 你周圍空域的班表航班 |
| `src/atc/traffic/engine.py` | AI 交通引擎：起降流程、跑道佔用、無線電對話 |
| `src/atc/radio_out.py` | 播放佇列（你的 ATC 優先，AI 對話排後面） |
| `src/atc/app.py` | 把上面全部串起來 |

## 目前限制 / 還沒驗證的地方（老實說）

- **我是在 Linux 上寫的，沒辦法實際開 MSFS 測**。SimBrief 解析、階段判斷、GSX 邏輯、Gemini 流程都有單元測試，但 SimConnect 和 GSX 真機要你在 Windows 上試。
- **GSX 選單檔位置**不同版本不一樣，找不到時會用「主選單第 5 項 = Request Pushback」的預設值；不對的話在 `config.toml` 的 `gsx.menu_file` 手動指定。
- 推出後 GSX 會再問方向等問題，目前要你自己在 GSX 選單點。
- **頻率**是 Gemini 依機場自己編的（還沒接真實頻率資料庫），預設不強制你調 COM1（`require_frequency = false`）。
- **AeroDataBox 的 API 格式是我照記憶寫的**：寫這段的時候，雲端環境的網路連不到它的文件網站，沒辦法確認。解析的部分有盡量放寬，如果抓不到班表，開 `-v` 把錯誤貼給我。CSV 班表這條路是確定能用的。
- 空中交通只包含「你出發/目的地機場的航班」（因為只查這兩個機場的班表），所以巡航時看到的飛機會比較少，大多是跟你同一條航線的。
- AI 起飛後飛到 10 海里就消失，空中那層是照班表時間另外算位置的，兩邊不會無縫接起來。
- AI 交通目前只有**跑道起降**：AI 不會從登機門推出、不會走滑行道（沒有機場滑行道資料），是直接出現在跑道頭旁等待/五邊上，脫離跑道後就消失。空中航路上也還沒有 AI。
- AI 飛機的動作是我們自己算的簡化版（直線、固定下滑道），起落架、燈光還沒控制。
- **SimConnect 生 AI 那段完全沒在真機上測過**，如果飛機沒出現或亂飄，開 `-v` 把 log 貼給我。
- AI 對話也會用 Gemini TTS，交通多的話用量會增加；不想聽可以把 `traffic.radio_chatter` 關掉。
- Gemini 模型名稱會更新，如果出錯就去 `config.toml` 換成最新的。

## 測試

```bash
pip install -e .[dev]
pytest
```
