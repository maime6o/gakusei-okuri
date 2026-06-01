# 学生課送り — システム仕様書

> **対象読者**: 将来のメンテナー・自分  
> **最終更新**: 2026-06-01  
> **実装バージョン**: v0.2.0  
> 本文書は推測ではなく実際のコードから起こしています。実装と食い違う部分は `TODO:` で明記します。

---

## 1. システム構成

### 1.1 技術スタック

| レイヤー | 技術 | バージョン |
|---|---|---|
| 言語 | Python | 3.11 |
| Web フレームワーク | FastAPI | 0.115.5 |
| ASGI サーバー | Uvicorn (standard extras) | 0.32.1 |
| WebSocket ライブラリ | websockets | 14.1 |
| モデル / バリデーション | Pydantic v2 | 2.10.3 |
| テストランナー | pytest + pytest-asyncio | 8.3.4 / 0.24.0 |
| テスト HTTP クライアント | httpx | 0.28.1 |
| フロントエンド | Vanilla JS (no framework) | — |

### 1.2 ディレクトリ構成

```
gakusei-okuri/
├── engine/              # ゲームエンジン（純粋関数・副作用なし）
│   ├── models.py        # Pydantic モデル定義（GameState, CardInstance など）
│   ├── actions.py       # apply_action() — 状態遷移の中核
│   ├── game.py          # create_game() — ゲーム初期化
│   ├── catalog.py       # catalog.json の読み込みと CardInstance 生成
│   ├── deck_builder.py  # FixedDeckBuilder / RandomDeckBuilder
│   └── hooks.py         # 能力フック（on_band_stat / on_play / on_judgment 等）
├── server/
│   ├── main.py          # FastAPI アプリ、REST / WebSocket エンドポイント
│   └── rooms.py         # インメモリ部屋レジストリ
├── data/
│   └── catalog.json     # カード定義（永続ファイル、読み取り専用）
├── static/              # フロントエンド（SPA）
│   ├── index.html
│   ├── app.js           # 全 UI ロジック（~1200行、フレームワークなし）
│   ├── style.css
│   ├── manifest.json    # PWA マニフェスト
│   ├── service-worker.js
│   ├── icon-192.png     # PWA アイコン（192×192）
│   └── icon-512.png     # PWA アイコン（512×512）
├── tests/
│   └── test_engine.py   # エンジン単体テスト 44件
├── render.yaml          # Render デプロイ設定
├── requirements.txt
└── .gitignore
```

### 1.3 engine/ と server/ の責務分離

**`engine/`**  
- ゲームルール・状態遷移のみ担当
- `apply_action(state, player_id, action) → (new_state, events)` が唯一の公開 API
- **純粋関数**: state を deep copy して返し、入力を一切変更しない
- ネットワーク・乱数注入・永続化には関与しない

**`server/`**  
- HTTP / WebSocket 接続の管理
- `rooms.py` でゲーム状態をインメモリ保持
- アクション受信 → `apply_action()` 呼び出し → 全接続にブロードキャスト
- 手札秘匿（`_player_view`）を担当

---

## 2. データの保持と永続性

### 2.1 保持場所一覧

| データ | 保持場所 | 揮発? |
|---|---|---|
| 部屋情報（Room オブジェクト） | `server/rooms.py` の `_rooms` dict（プロセスメモリ） | ✅ 揮発 |
| ゲーム状態（GameState） | `Room.state`（プロセスメモリ） | ✅ 揮発 |
| WebSocket 接続オブジェクト | `Room.connections` dict | ✅ 揮発 |
| カード定義 | `data/catalog.json`（ファイル） | ❌ 永続 |
| カタログキャッシュ | `engine/catalog.py` の `_catalog` モジュール変数 | ✅ 揮発（再起動でリセット） |
| フロントエンド静的ファイル | `static/`（ファイル） | ❌ 永続 |

### 2.2 部屋・ゲーム状態が消えるタイミング

| イベント | 結果 |
|---|---|
| Render Free tier のスリープ（15分無操作後） | **全部屋・全ゲーム状態が消滅** |
| `render.yaml` の再デプロイ | **全部屋・全ゲーム状態が消滅** |
| サーバープロセス再起動 | **全部屋・全ゲーム状態が消滅** |
| プレイヤーのブラウザリロード | WebSocket が再接続されれば状態復元（ゲームがまだ存在する場合） |

> `rooms.py` 冒頭コメント: _"All room data is lost on server restart / Render sleep+wake."_

### 2.3 既知の問題：部屋の削除がない

`delete_room()` は実装されているが呼ばれていない。ゲーム終了後も部屋は `_rooms` dict に残り続ける。長時間運用するとメモリが増加する。

### 2.4 catalog.json の位置づけ

- `engine/catalog.py` が起動後初回アクセス時に読み込み、`_catalog` モジュール変数にキャッシュ
- 読み取り専用。ゲーム中に変更されることはない
- `data/catalog.json` のスキーマ: `{"members":[...], "supports":[...], "antis":[...], "incidents":[...]}`

---

## 3. ゲームエンジン仕様

### 3.1 状態モデル（GameState）

```
GameState
├── game_id: str
├── phase: Phase（lobby/mulligan/action/live_processing/sotai/game_over）
├── players: List[PlayerState]
│   ├── player_id: str（"player_0", "player_1", ...）
│   ├── name: str
│   ├── deck: List[CardInstance]
│   ├── hand: List[CardInstance]
│   ├── field_members: List[CardInstance]  # 場に出たがバンド未結成のメンバー
│   ├── bands: List[Band]
│   │   ├── band_id: str
│   │   ├── members: List[CardInstance]
│   │   ├── live_draw / live_music / live_human: int  # ライブ計算値
│   │   └── did_live_this_turn: bool
│   ├── anti_zone: List[CardInstance]      # セットしたアンチカード
│   ├── discard: List[CardInstance]
│   ├── cumulative_mobilization: int       # 累計動員数
│   ├── music_score: int                   # 累計音楽性
│   ├── performance_record: int            # 活動実績（初期値4）
│   ├── mulligan_done: bool
│   └── cannot_play_member: bool           # アンチ効果による制限
├── current_player_idx: int
├── actions_remaining: int                 # 1ターン3行動
├── incident_deck: List[CardInstance]
├── incident_discard: List[CardInstance]
├── target_mobilization: int               # 80/120/160
├── winner_id: Optional[str]
├── event_log: List[str]
├── sotai_context: Optional[SotaiContext]
│   ├── victim_player_id, band_id
│   ├── nominator_player_id
│   ├── incident_name, severity, judgment_value
├── pending_band_processes: List[PendingProcess]  # SOTAI 割り込み後の未処理バンド
└── last_live_results: List[LiveBandResult]       # フロント演出用構造化データ
    ├── band_id, members（LiveMemberSummary[]）
    ├── draw_total, music_total, human_total
    ├── judgment_value, multiplier, num_bands
    ├── incident_name, incident_severity
    ├── success: bool
    ├── mobilization_gain, music_gain
```

### 3.2 フェーズ遷移

```
[ゲーム作成]
     │
     ▼
 MULLIGAN ────── 全員 mulligan 完了 ──────► ACTION
                                              │
                                        (3行動消費)
                                        draw / play_member / form_band
                                        disband / use_support / set_anti
                                              │
                                         end_turn
                                              │
                                      LIVE_PROCESSING
                                      （バンドごとに順次処理）
                                              │
                    ┌──── バンド成功 ─────────┤
                    │                         │
                    │                    バンド失敗
                    │                         │
                    │                       SOTAI ◄──────────────┐
                    │                     (choose_sotai)          │
                    │                         │ 残バンドがあれば  │
                    │              LIVE_PROCESSING（再開）─── バンド失敗──┘
                    │                         │ 全バンド完了
                    │                         ▼
                    └──────────────────── ACTION（次のプレイヤー）
                                              │
                                       目標動員数達成
                                              │
                                          GAME_OVER
```

**各フェーズのルール:**
- **MULLIGAN**: 全プレイヤー同時に実施（先着順）。キープ or 5枚引き直し（1回限り）
- **ACTION**: current_player のみ操作可。3行動/ターン。行動ごとに1消費（EndTurn はコスト0）
- **LIVE_PROCESSING**: バンドを1個ずつ処理。外部から見えない内部フェーズ（即座に SOTAI か ACTION に遷移）
- **SOTAI**: nominator（次の順番のプレイヤー）のみ `choose_sotai` を実行可能

### 3.3 判定式

```
judgment_value = round(effective_human × (1 + (num_bands - 1) × 0.17))
```

| バンド数 | 係数 |
|---|---|
| 1 | 1.00 |
| 2 | 1.17 |
| 3 | 1.34 |
| 4 | 1.51 |

- `effective_human` = バンドメンバーの human 合計 + `on_judgment` アビリティ補正 + アンチカード補正
- `num_bands` = 現在のプレイヤーの総バンド数（判定対象バンドを含む）
- **成功条件**: `judgment_value ≤ incident_severity`
- **失敗条件**: `judgment_value > incident_severity`

**事件デッキ（合計30枚）の severity 分布:**

| severity | 枚数 | カード名 |
|---|---|---|
| 0 | 4 | 平和な一日（常時成功） |
| 4 | 3 | 軽微な遅刻 |
| 5 | 6 | 会計報告ミス、終電逃した |
| 6 | 3 | 恋愛のもつれ |
| 7 | 8 | 騒音苦情、備品破損、機材の借りパク疑惑 |
| 8 | 4 | 飲酒トラブル、先輩との確執 |
| 9 | 1 | ボヤ騒ぎ |
| 10 | 1 | SNS炎上 |

**バランス試算（事件発生率）:**

|  | バンド1個 | バンド2個 | バンド3個 |
|---|---|---|---|
| low human (2) | 0% | 0% | 0% |
| mid human (6) | 13.3% | **53.3%** | 80.0% |
| high human (10) | 53.3% | 86.7% | 96.7% |

事件デッキが尽きると discard をシャッフルして再利用する（循環デッキ）。

### 3.4 活動実績システム

- 初期値: **4**
- メンバーカードを場に出す条件: `card.music ≤ player.performance_record`
- ライブ成功ごとに +1
- 上限なし

music 値の分布例: 1〜3（低コスト）、4（中コスト）、5〜6（高コスト）

### 3.5 学生課送りの逐次処理

エンジンはバンドの失敗を1件ずつ処理する:

1. `EndTurn` → `_process_live_phase()` がバンドを順次処理
2. バンドNが失敗 → `SotaiContext` を設定、残バンドを `pending_band_processes` に保存、phase=SOTAI で停止
3. Nominator が `choose_sotai` を送信 → `_handle_sotai()` が実行
   - `last_live_results` をリセット
   - `pending_band_processes` のバンドを順次処理
   - 再び失敗した場合は 2. に戻る
4. 全バンド処理完了 → `_end_party()` → 次のプレイヤーの ACTION フェーズ

**保証**: `last_live_results` の最後のエントリが失敗の場合、それ以降のバンドは含まれない（エンジンが即停止するため）。

---

## 4. 通信仕様

### 4.1 REST エンドポイント

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/healthz` | ヘルスチェック。`{"status":"ok"}` を返す |
| POST | `/rooms` | 部屋作成（ホスト名・目標動員数を指定） |
| POST | `/rooms/hotseat` | ホットシート用一括作成（全プレイヤー名を一度に指定し即ゲーム開始） |
| POST | `/rooms/{code}/join` | 部屋に参加 |
| POST | `/rooms/{code}/start` | ゲーム開始（ホストが呼ぶ） |
| GET | `/rooms/{code}` | 部屋情報取得（参加者一覧・開始済み判定） |

目標動員数は `80 / 120 / 160` の3択のみ受け付ける。部屋コードは5文字の大文字英字（例: `ABCDE`）。

### 4.2 WebSocket

**接続 URL**: `ws(s)://{host}/ws/{code}/{player_name}`

接続直後にサーバーから現在の状態が即座に送信される。

**サーバー → クライアント（2種類）:**

```jsonc
// ゲーム開始前（ロビー状態）
{"type": "room", "code": "ABCDE", "players": ["Alice", "Bob"]}

// ゲーム開始後（毎アクション後にブロードキャスト）
{"type": "state", "state": { /* _player_view で加工された GameState */ }}

// エラー（送信者のみに返す）
{"type": "error", "message": "あなたの手番ではありません"}
```

**クライアント → サーバー（アクション送信）:**

```jsonc
{"type": "draw"}
{"type": "play_member", "card_instance_id": "abc12345"}
{"type": "form_band", "member_instance_ids": ["id1", "id2", "id3"]}
{"type": "disband", "band_id": "xyz99"}
{"type": "use_support", "card_instance_id": "abc12345"}
{"type": "set_anti", "card_instance_id": "abc12345"}
{"type": "reveal_anti", "card_instance_id": "abc12345"}
{"type": "end_turn"}
{"type": "mulligan", "keep": true}
{"type": "choose_sotai", "member_instance_id": "abc12345"}
```

### 4.3 手札秘匿（`_player_view`）

`server/main.py` の `_player_view()` が各プレイヤーへの送信時に加工する:

- **自分の手札**: そのまま送信
- **他プレイヤーの手札**: `{"hidden": true, "count": N}` に置換（内容は不明、枚数のみ公開）
- **他プレイヤーのアンチカード（表向き）**: そのまま送信（全員が見える）
- **他プレイヤーのアンチカード（裏向き）**: `{"face_down": true, "instance_id": "..."}` に置換（カード種別は不明）

### 4.4 /healthz の役割

- Render がデプロイ後・稼働中に定期的に呼ぶヘルスチェックエンドポイント
- `render.yaml` の `healthCheckPath: /healthz` で参照されている
- **追加で**: cron-job.org 等の外部サービスから 10分おきに ping することで Render Free tier のスリープを防ぐ（手動設定が必要）

---

## 5. カードシステム

### 5.1 catalog.json の構造

```json
{
  "members":  [ CatalogCard, ... ],  // 35種
  "supports": [ CatalogCard, ... ],  // 8種
  "antis":    [ CatalogCard, ... ],  // 6種（うち2種は copies=0 で実際のデッキに非収録）
  "incidents":[ CatalogCard, ... ]   // 12種
}
```

**CatalogCard フィールド:**

| フィールド | 型 | 説明 |
|---|---|---|
| `id` | int? | メンバーカードのみ付番 |
| `name` | str | カード名 |
| `kind` | str | `member/support/anti/incident` |
| `part` | str? | パート（Vo/Gt/Ba/Dr/Key/特殊） |
| `draw` | int | 集客値（ライブ成功時の動員数） |
| `music` | int | 音楽性（プレイコスト兼ライブ成功時の音楽性） |
| `human` | int | 人間値（高いほど事件リスク上昇） |
| `ability` | Ability? | 能力定義 |
| `phase` | str? | サポート/アンチカードが使用可能なフェーズ |
| `effect` | str? | サポート/アンチカードの効果コード |
| `severity` | int? | 事件カードの事件性（0=常時成功） |
| `copies` | int | デッキへの収録枚数（デフォルト1） |

### 5.2 プレイヤーデッキの構成

| カード種別 | 枚数 |
|---|---|
| メンバー | 38枚 |
| サポート | 8枚 |
| アンチ | 4枚（copies≥1のものだけ） |
| **合計** | **50枚** |

全プレイヤーが同一の構成（FixedDeckBuilder）。seed が同じなら配列順も同一だが shuffle は player index を seed に加算するため各プレイヤーで異なる配列になる。

### 5.3 能力フック

**実装済み（エンジンで動作するもの）:**

| hook / type | 効果コード例 | 動作タイミング |
|---|---|---|
| `on_band_stat` / `static` | `draw+2`, `human-1`, `music+3_human+1` | バンド結成時の stat 計算 |
| `on_play` / `on_play` | `draw_card`, `mobilization+2_once` | メンバーを場に出した時 |
| `on_form` / `on_play` | `action+1` | バンドを結成した時 |
| `on_judgment` / `judgment` | `human-2`, `severity-1`, `success_draw+3`, `success_music+3`, `success_draw+5_once` | 事件判定時 |
| `on_sotai` / `special` | `学生課送りの指名対象に選べない` | 学生課送り指名時（actions.py で直接処理） |

**未実装（no-op、ログのみ出力）:**

| カード名 | type | hook | 効果説明 |
|---|---|---|---|
| 女王様ベーシスト | activated | on_play | 出す時手札1枚捨てる → draw+1 |
| 努力型ギターヒーロー | passive | on_turn_start | 自ターン開始時1枚引く |
| セッション中毒 | conditional | on_band_stat | バンド4人以上なら music+2 |
| 器用貧乏 | special | on_form | 不足パート1つを補う |
| コーラス要員 | conditional | on_band_stat | 同バンドに他Voがいれば music+2 |
| 機材に詳しい人 | special | on_event | 機材トラブル系の悪影響を無効 |
| DTMマニア | special | on_form | 結成時、人数を1人ぶん水増し |
| 打ち上げ要員 | activated | action | このカードを捨て2枚引く（行動1回） |
| 卒論が忙しい人 | conditional | on_play | 場に出た時1枚引く; ライブ後デッキに戻る |

**サポートカード実装状況:**

| カード名 | effect | 実装 |
|---|---|---|
| 差し入れ | `draw2` | ✅ |
| 練習スタジオ確保 | `music+3` | TODO: 実装コードが見当たらない |
| ビラ配り | `draw+3` | TODO: 実装コードが見当たらない |
| 助っ人ヘルプ | `free_play_member` | ❌ スキップ（コメントあり） |
| 顧問の口添え | `human-3` | TODO: 実装コードが見当たらない |
| 機材車 | `draw+2` | TODO: 実装コードが見当たらない |
| 打ち上げで結束 | `redraw_hand` | ✅ |
| アンコール | `encore` | ❌ 実装なし |

> TODO: サポートカード効果（`music+N`, `draw+N`, `human-N`, `encore`）がアクションフェーズで使用可能かどうか、および `_apply_support_effect_action` での実装状況を再確認すること。

**アンチカード実装状況（デッキ収録分のみ）:**

| カード名 | phase | effect | 実装 |
|---|---|---|---|
| 通報 | judgment | `severity+4` | ✅ |
| 苦情の電話 | live | `draw-3` | ✅ |
| 機材トラブル | live | `music-3` | ✅ |
| 練習不足の指摘 | judgment | `human+3` | ✅ |

copies=0（未収録）: 部室の鍵がない（`no_play_member`）、ライバルの妨害（`halve_draw`）

### 5.4 DeckBuilder

| クラス | 状態 |
|---|---|
| `FixedDeckBuilder` | ✅ 実装済み。全プレイヤーが同一の50枚構成。seed で shuffle |
| `RandomDeckBuilder` | ❌ インターフェースのみ（M4 TODO）。制約定数のみ定義済み（MIN_MEMBERS=35, MAX_SUPPORT_ANTI=15 等） |

事件デッキも `FixedDeckBuilder` で30枚生成。尽きたら discard をシャッフルして再利用。

---

## 6. デプロイ・運用

### 6.1 Render 設定

| 項目 | 値 |
|---|---|
| Runtime | Python |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn server.main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/healthz` |
| 環境変数 | `PYTHON_VERSION=3.11` |

`render.yaml` にこれらが定義されているが、Render ダッシュボードの「Manual Deploy」では自動検出されないため手動入力が必要。

### 6.2 Free Tier の制約

- **スリープ**: 15分間リクエストがないとプロセスが停止。次のアクセス時に起動（~30秒）
- **起動時にメモリクリア**: 全部屋・ゲーム状態が消える
- **対策**: cron-job.org 等から `/healthz` へ 10分おきに定期 ping（手動設定）

### 6.3 ローカル開発

```bash
make install    # 仮想環境作成 + 依存インストール
make run        # uvicorn --reload で起動（localhost:8000）
make test       # pytest tests/ -v
make lint       # py_compile による構文チェック
```

### 6.4 既知の制約と今後の課題

| 課題 | 詳細 |
|---|---|
| **永続化なし** | サーバー再起動で全ゲーム状態消滅。DB 接続は未実装 |
| **高 human カードが死にカード化** | human≥5 のメンバーをバンド2個以上に入れると事件率80〜90%超。現状の使い道が薄い |
| **未実装能力カード9枚** | 上記§5.3参照。ゲームに入っているが効果が発動しない |
| **RandomDeckBuilder 未実装** | 固定50枚デッキのみ。カスタムデッキ構築は M4 以降 |
| **部屋クリーンアップなし** | `delete_room()` は実装済みだが呼ばれていない。長時間運用でメモリリーク |
| **再接続時のゲーム復元不可** | 部屋が消えた（サーバー再起動）後に再接続しても復元できない |
| **サポートカード一部未実装** | `free_play_member`, `encore` が no-op |
| **on_turn_start フック未発動** | 「努力型ギターヒーロー」は毎ターン開始時のドローが発動しない |

---

## 7. テスト

計44件（`tests/test_engine.py`）。サーバー・フロントエンドのテストは現時点でなし。

| クラス | 件数 | 検証内容 |
|---|---|---|
| `TestDeckBuilder` | 6 | 50枚構成・種別枚数・事件デッキ約30枚・seed 再現性 |
| `TestGameCreation` | 6 | フェーズ初期値・初期手札5枚・プレイヤー数バリデーション・活動実績初期値4 |
| `TestMulligan` | 5 | キープ・引き直し・2回目NG・全員完了後ゲーム開始・フェーズ外操作 |
| `TestActionPhase` | 8 | 行動コスト・ドロー・手番外プレイヤー拒否・行動切れエラー・活動実績ゲーティング・バンド結成 |
| `TestLivePhase` | 5 | ライブ成功の動員加算・活動実績+1・事件発生SOTAI遷移・メンバー除外・事件時動員0 |
| `TestWinCondition` | 1 | 目標動員数到達で GAME_OVER + winner_id 設定 |
| `TestJudgmentBoundary` | 4 | jv=severity で成功・jv=severity+1 で失敗・human=0 常時成功・マルチバンド係数 |
| `TestStaticAbilities` | 3 | ムードメーカー（human-1）・カリスマOB（draw+2）・テクニカル神ドラマー（music+3_human+1）|
| `TestPerformanceRecord` | 3 | music値超過でプレイ拒否・以下で許可・活動実績解放で高musicカード解放 |
| `TestLiveBandResult` | 3 | 成功時 LiveBandResult フィールド検証・失敗時フィールド検証・**複数バンド失敗時の逐次SOTAI指名（2回）** |
