'use strict';
/**
 * ほーろっくよーがっく2026（目指せ最高のライブ）— SPA (M2/M3)
 *
 * モード:
 *   hotseat : 1台で複数人。手番が変わるたびデバイスを渡す。
 *   online  : 各自の端末から接続。WS は常時接続。
 *
 * 画面遷移:
 *   lobby → hotseat_setup → game (handoff を挟む)
 *   lobby → waiting       → game (online)
 */

// ── グローバル状態 ─────────────────────────────────────────────────────────
const S = {
  screen: 'lobby',       // 現在の画面 ID
  mode: null,            // 'hotseat' | 'online'
  roomCode: null,
  myName: null,          // WS 接続中のプレイヤー名（ホットシートでは切り替わる）
  myPlayerId: null,
  gameState: null,
  ws: null,
  sel: [],               // 選択中カードの instance_id[]
  handoffTarget: null,   // ハンドオフ先の名前
  allPlayerNames: [],    // ホットシート用：全員の名前リスト
};

// カード詳細表示用キャッシュ（instance_id → CardInstance）
const _cardCache = {};

// ライブ演出状態
const LP = {
  active: false,
  bandResults: [],
  bandIdx: 0,
  step: 0,
  postState: null,
  isActiveLivePlayer: false,
  autoTimer: null,
};

// ── BGM ────────────────────────────────────────────────────────────────────
const BGM = {
  tracks: {
    lobby: new Audio('/sounds/bgm_lobby.mp3'),
    game:  new Audio('/sounds/bgm_game.mp3'),
  },
  current:  null,
  muted:    true,
  unlocked: false,
  volume:   0.3,
};
BGM.tracks.lobby.loop   = true;
BGM.tracks.game.loop    = true;
BGM.tracks.lobby.volume = BGM.volume;
BGM.tracks.game.volume  = BGM.volume;

function bgmPlay(name) {
  if (BGM.current === name) return;
  if (BGM.current && BGM.tracks[BGM.current]) {
    BGM.tracks[BGM.current].pause();
    BGM.tracks[BGM.current].currentTime = 0;
  }
  BGM.current = name;
  if (name && !BGM.muted && BGM.tracks[name]) {
    BGM.tracks[name].play().catch(() => {});
  }
}

function bgmStop() { bgmPlay(null); }

function bgmToggleMute() {
  BGM.muted = !BGM.muted;
  const btn = document.getElementById('bgm-mute-btn');
  if (btn) btn.textContent = BGM.muted ? '🔇' : '🔊';
  if (BGM.muted) {
    if (BGM.current && BGM.tracks[BGM.current]) BGM.tracks[BGM.current].pause();
  } else {
    if (BGM.current && BGM.tracks[BGM.current]) BGM.tracks[BGM.current].play().catch(() => {});
  }
}

function bgmSetVolume(val) {
  BGM.volume = val / 100;
  for (const t of Object.values(BGM.tracks)) t.volume = BGM.volume;
  const btn = document.getElementById('bgm-mute-btn');
  if (btn) btn.textContent = BGM.volume === 0 ? '🔇' : '🔊';
}

function _bgmUnlock() {
  if (BGM.unlocked) return;
  BGM.unlocked = true;
  bgmPlay('lobby');
}
document.addEventListener('click',      _bgmUnlock, { once: true });
document.addEventListener('touchstart', _bgmUnlock, { once: true });

// ── DOM ────────────────────────────────────────────────────────────────────
const $  = id => document.getElementById(id);
const esc = s  => String(s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

function updatePhaseTag() {
  const pt = $('phase-tag');
  if (!pt) return;

  if (LP.active) {
    const stepNames = ['ライブ開始', '集計・判定値', '事件めくり', '判定結果'];
    pt.style.display = '';
    pt.textContent = `ライブ処理 ${LP.bandIdx + 1}/${LP.bandResults.length}バンド — ${stepNames[LP.step] || ''}`;
    pt.className = 'phase-tag active';
    return;
  }

  const gs = S.gameState;
  const inGame = ['mulligan', 'game'].includes(S.screen);
  if (!gs || !inGame) { pt.style.display = 'none'; return; }

  const cp = gs.players?.[gs.current_player_idx];
  const isMyTurn = gs.phase === 'action' && cp?.player_id === S.myPlayerId;
  pt.style.display = '';
  pt.textContent = phaseLabel(gs.phase) + (isMyTurn ? ' あなたの手番' : '');
  pt.className = 'phase-tag' + (isMyTurn ? ' active' : '');
}

function render() {
  updatePhaseTag();
  $('actions-toolbar').style.display = 'none';
  $('actions-toolbar').innerHTML = '';

  switch (S.screen) {
    case 'lobby':         renderLobby();        break;
    case 'hotseat_setup': renderHotseatSetup(); break;
    case 'waiting':       renderWaiting();      break;
    case 'handoff':       renderHandoff();      break;
    case 'mulligan':      renderMulligan();     break;
    case 'game':          renderGame();         break;
    case 'connecting':    renderConnecting();   break;
    case 'live_pres':     renderLivePres();     break;
  }
}

// ── ロビー ─────────────────────────────────────────────────────────────────
function renderLobby() {
  $('main-content').innerHTML = `
    <div class="lobby-wide">

      <!-- Hero -->
      <div class="lobby-hero">
        <div class="lobby-hero-text">
          <div class="lobby-hero-title">🎸 ほーろっくよーがっく2026</div>
          <div class="lobby-hero-sub">目指せ最高のライブ — 2〜4人用バンドカードゲーム</div>
        </div>
        <div class="lobby-title-img-wrap">
          <img class="lobby-title-img" src="/images/title.png" alt=""
               onerror="this.parentNode.style.display='none'">
        </div>
      </div>

      <!-- 2-column grid -->
      <div class="lobby-grid">

        <!-- Left: rules -->
        <div class="lobby-left">

          <div class="card-section">
            <h3>🏆 勝利条件 &amp; 基本ルール</h3>
            <div class="rulebook">
              目標動員数（80 / 120 / 160 から選択）に先に到達したプレイヤーの勝利。<br>
              ゲーム開始前に手札の引き直し（マリガン）を1回だけ行えます。

              <h4>🔄 ターンの流れ</h4>
              <div class="turn-flow">
                <span class="turn-step">①ターン開始</span>
                <span class="turn-step highlight">②行動フェーズ</span>
                <span class="turn-step highlight">③ライブフェーズ</span>
                <span class="turn-step">④事件確認</span>
                <span class="turn-step">⑤事件判定</span>
                <span class="turn-step">⑥動員数確認</span>
                <span class="turn-step">⑦ターン終了</span>
              </div>
              全員が初ターンを終えると、以降は毎ターン開始時に<b>自動で1枚ドロー</b>（行動ポイント消費なし）。
            </div>
          </div>

          <div class="card-section">
            <h3>📕 用語説明</h3>
            <div class="glossary">
              <div class="gloss-item">
                <span class="gloss-term">活動実績</span>
                <span class="gloss-desc">バンドメンバーを出すためのリソース。ライブ成功のたびに+1。<br>音楽性コストを支払ってメンバーを出すと減少する。</span>
              </div>
              <div class="gloss-item">
                <span class="gloss-term">バンドメンバー</span>
                <span class="gloss-desc">バンドを構成するカード。集客力・音楽性・対応力・パート・性別などを持つ。<br>「活動実績 ≥ 音楽性」のメンバーだけ場に出せる。<br>
                <span class="rule-example">例）活動実績8 → 音楽性3のカードを出す → 活動実績5に減少</span></span>
              </div>
              <div class="gloss-item">
                <span class="gloss-term">バンド</span>
                <span class="gloss-desc">メンバー3人以上で結成。6人以上は事件カードを2枚引く。パート・性別の組み合わせで編成ボーナスあり。</span>
              </div>
              <div class="gloss-item">
                <span class="gloss-term">サポートカード</span>
                <span class="gloss-desc">自ターン中に使う補助カード。ドロー・動員数操作・ライブ強化など。</span>
              </div>
              <div class="gloss-item">
                <span class="gloss-term">アンチカード</span>
                <span class="gloss-desc">事前に伏せておくと相手ターン中に自動発動するトラップ。事件性を上げたりライブを妨害する。</span>
              </div>
            </div>
          </div>

          <div class="card-section">
            <h3>⚡ 行動フェーズ（行動ポイント3）</h3>
            <div class="rulebook">
              <h4>① ドロー</h4>
              山札から1枚引く。

              <h4>② メンバーをフィールドに出す</h4>
              手札から活動実績以下の音楽性のメンバーを出す。音楽性分だけ活動実績が減る。

              <h4>③ バンドを結成する</h4>
              フィールドの無所属メンバー3人以上でバンドを結成。パート・性別によって編成ボーナスが付く。

              <h4>④ バンドを解散する</h4>
              バンドを解散。メンバーは無所属としてフィールドに残る。

              <h4>⑤ サポートカードを使う</h4>
              手札のサポートカードを使って補助効果を発動。

              <h4>⑥ アンチカードをセットする</h4>
              アンチカードを伏せて置く。相手のターンに自動発動。

              <h4>⑦ 対バンする</h4>
              自バンドと相手バンドの音楽性を比較。勝利すると<b>自バンドの音楽性×2</b>の動員数を相手から奪える。相手の音楽性は非公開。
            </div>
          </div>

          <div class="card-section">
            <h3>⚡ ライブ・事件フェーズ</h3>
            <div class="rulebook">
              行動フェーズ終了時、バンドが1つ以上あれば各バンドが自動でライブを行う。<br>
              各バンドごとに事件カードを1枚引き、内容を確認する。

              <h4>ライブ失敗</h4>
              <div class="rule-indent">事件性 ＞ バンドの対応力 → ライブ失敗。メンバー1名が学生課送り（ゲームから除外）。</div>

              <h4>ライブ成功</h4>
              <div class="rule-indent">対応力 ≥ 事件性 → ライブ成功。集客力の合計が動員数に加算され、活動実績+1。</div>

              ゲーム終了後は動員数を確認し、目標に達したプレイヤーがいれば勝利。達していなければ次のプレイヤーのターンへ。
            </div>
          </div>

        </div><!-- /lobby-left -->

        <!-- Right: band bonuses + play -->
        <div class="lobby-right">

          <div class="card-section">
            <h3>🎸 バンド編成ボーナス</h3>
            <div class="band-bonus-table">
              <div class="bbt-row"><span class="bbt-name">無もなきスリーピース</span><span class="bbt-cond">Gt・Ba・Dr（3人）</span><span class="bbt-bonus">音+2 応+1</span></div>
              <div class="bbt-row"><span class="bbt-name">通常バンド</span><span class="bbt-cond">Gt×2・Ba・Dr（4人）</span><span class="bbt-bonus">音+2 応+3</span></div>
              <div class="bbt-row"><span class="bbt-name">ガールズバンド</span><span class="bbt-cond">全員 Female</span><span class="bbt-bonus">集+3 応+1</span></div>
              <div class="bbt-row"><span class="bbt-name">ボーイズバンド</span><span class="bbt-cond">全員 Male</span><span class="bbt-bonus">集+1 音+1 応+1</span></div>
            </div>
            <div style="font-size:11px;color:var(--muted);margin-top:4px">
              スリーピース⇔通常バンドは排他。ガールズ⇔ボーイズも排他。それ以外の組み合わせは複合発動。
            </div>
          </div>

          <div class="card-section lobby-play-section">
            <h3>🎮 ホットシート</h3>
            <p style="color:var(--muted);font-size:12px">1台を順番に回して遊びます（2〜4人）。</p>
            <button class="btn btn-primary btn-lg" onclick="S.screen='hotseat_setup';render()">
              ホットシートで始める
            </button>
          </div>

          <div class="card-section">
            <h3>📱 オンライン対戦</h3>
            <div class="online-subsection">
              <div class="online-subsection-label">部屋を作る</div>
              <label>あなたの名前</label>
              <input id="create-name" type="text" placeholder="例: Alice" maxlength="12">
              <label>目標動員数</label>
              <select id="create-target">
                <option value="80">80（短め）</option>
                <option value="120" selected>120（標準）</option>
                <option value="160">160（長め）</option>
              </select>
              <button class="btn btn-primary" onclick="onCreateOnline()">部屋を作る</button>
            </div>
            <div class="online-subsection">
              <div class="online-subsection-label">部屋に参加する</div>
              <label>あなたの名前</label>
              <input id="join-name" type="text" placeholder="例: Bob" maxlength="12">
              <label>部屋コード（5文字）</label>
              <input id="join-code" type="text" placeholder="ABCDE" maxlength="5"
                     style="text-transform:uppercase;letter-spacing:4px;font-size:18px;text-align:center">
              <button class="btn btn-secondary" onclick="onJoinOnline()">コードで参加</button>
            </div>
          </div>

          <div id="lobby-error" class="error-banner"></div>
        </div><!-- /lobby-right -->

      </div><!-- /lobby-grid -->
    </div>`;
}

async function onCreateOnline() {
  const name   = $('create-name').value.trim();
  const target = parseInt($('create-target').value);
  if (!name) { showLobbyErr('名前を入力してください'); return; }
  const res = await api('POST', '/rooms', { host_name: name, target_mobilization: target });
  if (!res.ok) { showLobbyErr(await res.text()); return; }
  const d = await res.json();
  S.mode     = 'online';
  S.myName   = name;
  S.roomCode = d.code;
  S.screen   = 'waiting';
  render();
  connectWs();
}

async function onJoinOnline() {
  const name = $('join-name').value.trim();
  const code = ($('join-code').value.trim()).toUpperCase();
  if (!name)         { showLobbyErr('名前を入力してください'); return; }
  if (code.length !== 5) { showLobbyErr('部屋コードは5文字です'); return; }
  const res = await api('POST', `/rooms/${code}/join`, { player_name: name });
  if (!res.ok) { showLobbyErr(await res.text()); return; }
  S.mode     = 'online';
  S.myName   = name;
  S.roomCode = code;
  S.screen   = 'waiting';
  render();
  connectWs();
}

function showLobbyErr(msg) {
  const el = $('lobby-error');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg);
  el.classList.add('show');
}

// ── ホットシート設定 ────────────────────────────────────────────────────────
function renderHotseatSetup() {
  $('main-content').innerHTML = `
    <div class="lobby-wrap">
      <h2>ホットシート設定</h2>
      <div class="card-section">
        <h3>プレイヤー名を入力</h3>
        <label>目標動員数</label>
        <select id="hs-target">
          <option value="80">80（短め）</option>
          <option value="120" selected>120（標準）</option>
          <option value="160">160（長め）</option>
        </select>
        <div id="hs-players">
          ${[1,2,3,4].map(i=>`
            <div style="display:flex;align-items:center;gap:8px;margin-top:6px">
              <span style="color:var(--muted);width:14px">${i}</span>
              <input id="hs-p${i}" type="text" placeholder="${i<=2?'必須':'任意（'+i+'人目）'}"
                     maxlength="12" style="flex:1" ${i>2?'':'required'}>
            </div>`).join('')}
        </div>
        <div id="hs-error" class="error-banner" style="margin-top:8px"></div>
        <button class="btn btn-primary" style="margin-top:12px" onclick="onStartHotseat()">
          ゲーム開始
        </button>
        <button class="btn btn-secondary" style="margin-top:6px" onclick="S.screen='lobby';render()">
          ← 戻る
        </button>
      </div>
    </div>`;
}

async function onStartHotseat() {
  const names = [1,2,3,4]
    .map(i => ($(`hs-p${i}`)?.value || '').trim())
    .filter(Boolean);
  if (names.length < 2) {
    $('hs-error').textContent = '2人以上の名前を入力してください';
    $('hs-error').classList.add('show');
    return;
  }
  const target = parseInt($('hs-target').value);
  const res = await api('POST', '/rooms/hotseat', { player_names: names, target_mobilization: target });
  if (!res.ok) {
    $('hs-error').textContent = await res.text();
    $('hs-error').classList.add('show');
    return;
  }
  const d = await res.json();
  S.mode           = 'hotseat';
  S.allPlayerNames = names;
  S.roomCode       = d.code;
  S.myName         = names[0];
  S.screen         = 'connecting';
  render();
  connectWs();
}

// ── オンライン待機室 ────────────────────────────────────────────────────────
function renderWaiting() {
  const players   = S.gameState?.players || [];
  const isMyTurn  = players.length > 0 && (
    (typeof players[0] === 'string' ? players[0] : players[0].name) === S.myName
  );

  $('main-content').innerHTML = `
    <div class="lobby-wrap">
      <h2>待機中…</h2>
      <div class="card-section">
        <h3>部屋コード（タップでコピー）</h3>
        <div class="room-code" onclick="copyCode()">${S.roomCode}</div>
        <div class="room-code-hint">友達にこのコードを教えてください</div>
      </div>
      <div class="card-section">
        <h3>参加者</h3>
        <ul class="player-list">
          ${players.map((p,i) => {
            const n = typeof p === 'string' ? p : p.name;
            return `<li>${esc(n)}${i===0?'<span class="badge">ホスト</span>':''}</li>`;
          }).join('')}
        </ul>
      </div>
      ${isMyTurn ? `
        <button class="btn btn-primary" onclick="onStartOnline()"
                ${players.length < 2 ? 'disabled' : ''}>
          ゲーム開始（${players.length}人）
        </button>` :
        `<p style="text-align:center;color:var(--muted)">ホストの開始を待っています…</p>`}
    </div>`;
}

async function onStartOnline() {
  const res = await api('POST', `/rooms/${S.roomCode}/start`, {});
  if (!res.ok) toast('開始できませんでした');
}

function copyCode() {
  navigator.clipboard?.writeText(S.roomCode).then(() => toast('コードをコピーしました！'));
}

// ── ハンドオフ（ホットシートのみ） ────────────────────────────────────────
function renderHandoff() {
  $('main-content').innerHTML = `
    <div class="lobby-wrap" style="justify-content:center;min-height:70vh;text-align:center">
      <div style="font-size:56px;margin-bottom:16px">📱</div>
      <h2 style="margin-bottom:8px">${esc(S.handoffTarget)} さんへ</h2>
      <p style="color:var(--muted);margin-bottom:24px">デバイスを渡してください</p>
      <button class="btn btn-primary" style="font-size:16px;padding:14px 32px"
              onclick="onHandoffConfirm()">
        私は ${esc(S.handoffTarget)} です — 準備OK
      </button>
    </div>`;
}

function onHandoffConfirm() {
  S.myName = S.handoffTarget;
  S.handoffTarget = null;
  S.screen = 'connecting';
  render();
  reconnectWs();
}

// ── 接続中 ─────────────────────────────────────────────────────────────────
function renderConnecting() {
  $('main-content').innerHTML = `
    <div class="lobby-wrap" style="text-align:center;padding:60px 0">
      <p style="color:var(--muted)">接続中…</p>
    </div>`;
}

// ── マリガン ──────────────────────────────────────────────────────────────
function renderMulligan() {
  const gs = S.gameState;
  const me = gs?.players?.find(p => p.player_id === S.myPlayerId);
  if (!me) { $('main-content').innerHTML = '<p style="padding:20px">読み込み中…</p>'; return; }

  if (me.mulligan_done) {
    const waiting = gs.players.filter(p => !p.mulligan_done).map(p => p.name).join('、');
    $('main-content').innerHTML = `
      <div class="lobby-wrap" style="text-align:center">
        <p style="padding:20px 0">マリガン済み ✓</p>
        <p style="color:var(--muted)">待機中: ${esc(waiting)}</p>
      </div>`;
    return;
  }

  if (!S.mulliganSelected) S.mulliganSelected = new Set();
  const sel = S.mulliganSelected;
  const n = sel.size;

  const cardsHtml = me.hand.map(c => {
    const isSel = sel.has(c.instance_id);
    return `<div class="card${isSel ? ' selected' : ''}"
                 onclick="toggleMulliganCard('${c.instance_id}')">
      ${cardInner(c, {showAbility: true})}
    </div>`;
  }).join('');

  const btnLabel = n > 0 ? `選択した ${n}枚を交換` : '全てキープ';
  const btnClass = n > 0 ? 'btn-primary' : 'btn-secondary';

  $('main-content').innerHTML = `
    <div class="lobby-wrap">
      <h2>${esc(me.name)} のマリガン</h2>
      <p style="color:var(--muted);font-size:12px;margin-bottom:8px">
        交換したいカードをタップして選択（複数可）。選択しない場合はそのままキープ。
      </p>
      <div class="cards-row" style="margin-bottom:12px">${cardsHtml}</div>
      <button class="btn ${btnClass}" style="width:100%" onclick="submitMulligan()">
        ${btnLabel}
      </button>
    </div>`;
}

function toggleMulliganCard(instanceId) {
  if (!S.mulliganSelected) S.mulliganSelected = new Set();
  if (S.mulliganSelected.has(instanceId)) {
    S.mulliganSelected.delete(instanceId);
  } else {
    S.mulliganSelected.add(instanceId);
  }
  renderMulligan();
}

function submitMulligan() {
  const discardIds = S.mulliganSelected ? [...S.mulliganSelected] : [];
  S.mulliganSelected = null;
  sendAction({ type: 'mulligan', discard_ids: discardIds });
}

// ── ゲーム盤面 ─────────────────────────────────────────────────────────────
function renderGame() {
  const gs = S.gameState;
  if (!gs) { $('main-content').innerHTML = '<p style="padding:20px">読み込み中…</p>'; return; }

  const me         = gs.players.find(p => p.player_id === S.myPlayerId);
  const cpIdx      = gs.current_player_idx;
  const cp         = gs.players[cpIdx];
  const isMyTurn   = gs.phase === 'action' && cp?.player_id === S.myPlayerId;
  const isSotai    = gs.phase === 'sotai'
                     && gs.sotai_context?.nominator_player_id === S.myPlayerId;
  const isOnline   = S.mode === 'online';

  let html = '<div class="board"><div class="game-layout"><div class="game-main">';

  // ── 勝利 ──
  if (gs.phase === 'game_over') {
    html += renderResultScreen(gs);
    $('main-content').innerHTML = html + '</div></div></div>';
    return;
  }

  // ── オンライン：相手ターン中の待機バナー ──
  if (isOnline && !isMyTurn && !isSotai && gs.phase === 'action') {
    html += `<div class="waiting-banner">⏳ ${esc(cp?.name ?? '?')} のターン中…</div>`;
  }

  // ── 動員数バー ──
  html += '<div class="mob-bars">';
  for (const p of gs.players) {
    const pct = Math.min(100, Math.round(p.cumulative_mobilization / gs.target_mobilization * 100));
    const isActive = p.player_id === cp?.player_id && gs.phase === 'action';
    html += `
      <div class="mob-bar-row">
        <span class="${isActive ? 'active-player' : ''}">${esc(p.name)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
        <span class="mob-val">${p.cumulative_mobilization}/${gs.target_mobilization}</span>
      </div>`;
  }
  html += '</div>';

  if (!me) { $('main-content').innerHTML = html + '</div></div></div>'; return; }

  // ── 自分のステータスチップ ──
  html += `
    <div class="status-bar">
      <div class="stat-chip accent">
        <span class="val">${me.performance_record}</span><span>活動実績</span>
      </div>
      <div class="stat-chip">
        <span class="val">${me.music_score}</span><span>音楽性累計</span>
      </div>
      <div class="stat-chip">
        <span class="val">${me.hand.length}</span><span>手札</span>
      </div>
      <div class="stat-chip">
        <span class="val">${me.deck.length}</span><span>山札</span>
      </div>
    </div>`;

  // ── 学生課送り指名UI ──
  if (isSotai && gs.sotai_context) {
    const ctx    = gs.sotai_context;
    const victim = gs.players.find(p => p.player_id === ctx.victim_player_id);
    const band   = victim?.bands?.find(b => b.band_id === ctx.band_id);
    const mems   = band ? (band.members || []) : [];
    html += `
      <div class="incident-banner">
        ⚡ 学生課送り指名 — 「${esc(ctx.incident_name)}」<br>
        <small>${esc(victim?.name)}のバンドからメンバー1名を選んでください</small>
      </div>
      <div class="cards-row">
        ${mems.map(m => `
          <div class="card"
               onclick="sendAction({type:'choose_sotai',member_instance_id:'${m.instance_id}'})"
               onmouseenter="onCardEnter(event,'${m.instance_id}')"
               onmouseleave="onCardLeave()"
               title="${esc(m.name)}">
            ${cardInner(m)}
          </div>`).join('')}
      </div>`;
  }

  // ── アンチカードの公開（オンライン：相手ターン中） ──
  if (isOnline && !isMyTurn && gs.phase === 'action') {
    const myAntis = me.anti_zone?.filter(c => c.face_down) || [];
    if (myAntis.length > 0) {
      html += `
        <div class="card-section" style="padding:10px;border:1px solid var(--warn)">
          <div style="font-size:12px;color:var(--warn);margin-bottom:6px">
            アンチカードを今公開できます
          </div>
          <div class="cards-row">
            ${myAntis.map(c => `
              <div class="card"
                   onclick="revealAnti('${c.instance_id}')"
                   onmouseenter="onCardEnter(event,'${c.instance_id}')"
                   onmouseleave="onCardLeave()"
                   title="${esc(c.name||'?')}">
                ${cardInner(c)}
              </div>`).join('')}
          </div>
        </div>`;
    }
  }

  // ── 自分の手札 ──
  html += `
    <div>
      <div class="section-title">手札（${me.hand.length}枚）</div>
      <div class="cards-row">
        ${(me.hand || []).map(c => cardHtml(c, {
          large:       true,
          selectable:  isMyTurn,
          selected:    S.sel.includes(c.instance_id),
          disabled:    c.kind === 'member' && c.music > me.performance_record,
          showAbility: true,
        })).join('')}
      </div>
    </div>`;

  // ── フィールド（バンド未所属） ──
  if (me.field_members?.length > 0) {
    html += `
      <div>
        <div class="section-title">フィールド — バンド未所属（${me.field_members.length}人）</div>
        <div class="cards-row">
          ${me.field_members.map(c => cardHtml(c, {
            small:      true,
            selectable: isMyTurn,
            selected:   S.sel.includes(c.instance_id),
          })).join('')}
        </div>
      </div>`;
  }

  // ── バンド ──
  if (me.bands?.length > 0) {
    html += `<div class="bands-section"><div class="section-title">バンド（${me.bands.length}/4）</div>`;
    for (const band of me.bands) {
      const mems    = band.members || [];
      const rawDraw = mems.reduce((s,m) => s + m.draw, 0);
      const rawMus  = mems.reduce((s,m) => s + m.music, 0);
      const rawHum  = mems.reduce((s,m) => s + m.human, 0);
      const bName   = getBandName(mems);
      html += `
        <div class="band-card">
          <div class="band-header">
            <span style="font-size:12px">🎸 ${bName ? `<b>${esc(bName)}</b>` : `バンド（${mems.length}人）`}</span>
            <div class="band-stats">
              <span style="color:#64b5f6">集${band.live_draw || rawDraw}</span>
              <span style="color:#ba68c8">音${band.live_music || rawMus}</span>
              <span style="color:#ef9a9a">応${band.live_human || rawHum}</span>
            </div>
            ${isMyTurn
              ? `<button class="btn btn-sm btn-secondary"
                         onclick="sendAction({type:'disband',band_id:'${band.band_id}'})">解散</button>`
              : ''}
          </div>
          <div class="cards-row">
            ${mems.map(m => cardHtml(m, {small: true})).join('')}
          </div>
        </div>`;
    }
    html += '</div>';
  }

  // ── アンチゾーン（自分の伏せカード） ──
  if (me.anti_zone?.length > 0) {
    html += `
      <div>
        <div class="section-title">アンチゾーン（伏せ: ${me.anti_zone.length}枚）</div>
        <div class="cards-row">
          ${me.anti_zone.map(c => cardHtml(c, {faceDownLabel: '伏せ中'})).join('')}
        </div>
      </div>`;
  }

  // ── 他プレイヤー（画像付き） ──
  for (const op of gs.players) {
    if (op.player_id === S.myPlayerId) continue;
    const handCount  = typeof op.hand === 'object' && !Array.isArray(op.hand)
                         ? op.hand.count : (op.hand?.length ?? 0);
    const isOpActive = op.player_id === cp?.player_id;
    html += `
      <div class="card-section opponent-section${isOpActive?' opponent-active':''}">
        <div class="opponent-header">
          <span class="opponent-name">${esc(op.name)}${isOpActive?' ◀ 手番':''}</span>
          <span class="opponent-meta">
            手札:${handCount}枚 &nbsp; 活動実績:${op.performance_record} &nbsp; 動員:${op.cumulative_mobilization}
          </span>
        </div>`;
    if ((op.field_members?.length ?? 0) > 0) {
      html += `
        <div>
          <div class="section-title" style="font-size:11px">フィールド（${op.field_members.length}人）</div>
          <div class="cards-row">
            ${op.field_members.map(m => cardHtml(m, {small: true})).join('')}
          </div>
        </div>`;
    }
    if ((op.bands?.length ?? 0) > 0) {
      html += `<div class="bands-section">`;
      for (const b of op.bands) {
        const ms      = b.members || [];
        const rawDraw = ms.reduce((s,m) => s + m.draw,  0);
        const rawMus  = ms.reduce((s,m) => s + m.music, 0);
        const rawHum  = ms.reduce((s,m) => s + m.human, 0);
        const musLabel = b.live_music === -1 ? '??' : (b.live_music || rawMus);
        const opBName  = getBandName(ms);
        html += `
          <div class="band-card">
            <div class="band-header">
              <span style="font-size:11px">🎸 ${opBName ? `<b>${esc(opBName)}</b>` : `バンド（${ms.length}人）`}</span>
              <div class="band-stats">
                <span style="color:#64b5f6">集${b.live_draw || rawDraw}</span>
                <span style="color:#ba68c8">音${musLabel}</span>
                <span style="color:#ef9a9a">応${b.live_human || rawHum}</span>
              </div>
            </div>
            <div class="cards-row">
              ${ms.map(m => cardHtml(m, {small: true})).join('')}
            </div>
          </div>`;
      }
      html += '</div>';
    }
    html += '</div>';
  }

  // close game-main, build sidebar log
  html += '</div>';

  const opNames  = gs.players.filter(p => p.player_id !== S.myPlayerId).map(p => p.name);
  const logItems = (gs.event_log || []).slice(-60).reverse();
  const logHtml  = logItems.map(l => {
    const cls = opNames.some(n => l.includes(n)) ? 'log-opponent' : '';
    return `<div class="log-entry ${cls}">${esc(l)}</div>`;
  }).join('');

  html += `
    <div class="game-sidebar">
      <div class="section-title" style="margin-bottom:6px;font-size:12px">イベントログ</div>
      <div class="log-panel">${logHtml}</div>
    </div>`;

  html += '</div></div>'; // game-layout + board
  $('main-content').innerHTML = html;

  // ツールバー（自分のターンのみ）
  if (isMyTurn) renderToolbar(me, gs);
}

// ── アクションツールバー ─────────────────────────────────────────────────
function renderToolbar(me, gs) {
  const tb     = $('actions-toolbar');
  tb.style.display = 'flex';
  const sel    = S.sel;
  const hand   = me.hand || [];
  const field  = me.field_members || [];

  const selHandMember  = sel.find(id => hand.find(c => c.instance_id === id && c.kind === 'member'));
  const selHandSupport = sel.find(id => hand.find(c => c.instance_id === id && c.kind === 'support' && c.phase === 'action'));
  const selHandAnti    = sel.find(id => hand.find(c => c.instance_id === id && c.kind === 'anti'));
  const selFieldIds    = sel.filter(id => field.find(c => c.instance_id === id));

  const apRemain = gs.actions_remaining;
  const apShow   = Math.min(apRemain, 6);
  const pips = Array.from({length: 6}, (_, i) =>
    `<div class="ap-pip${i < apShow ? '' : ' ap-pip-used'}"></div>`
  ).join('');
  const apExtra = apRemain > 6 ? `<span class="ap-extra">+${apRemain - 6}</span>` : '';

  tb.innerHTML = `
    <div class="ap-pips" title="残り行動ポイント: ${apRemain}">
      ${pips}${apExtra}
      <span class="ap-label">${apRemain}</span>
    </div>
    <button class="btn btn-secondary btn-sm" onclick="sendAction({type:'draw'})">
      ドロー
    </button>
    ${selHandMember ? `
      <button class="btn btn-primary btn-sm" onclick="onPlayMember()">
        メンバーを出す
      </button>` : ''}
    ${selFieldIds.length >= 3 ? `
      <button class="btn btn-primary btn-sm" onclick="onFormBand()">
        バンド結成（${selFieldIds.length}人）
      </button>` : ''}
    ${selHandSupport ? `
      <button class="btn btn-secondary btn-sm" onclick="onUseSupport()">
        サポート使用
      </button>` : ''}
    ${selHandAnti ? `
      <button class="btn btn-secondary btn-sm" onclick="onSetAnti()">
        アンチ伏せる
      </button>` : ''}
    ${me.bands?.length > 0 && gs.players.some(p => p.player_id !== S.myPlayerId && p.bands?.length > 0) ? `
      <button class="btn btn-secondary btn-sm" onclick="openTaibanModal()">
        🎸 対バン
      </button>` : ''}
    <button class="btn btn-sm" style="background:var(--warn);color:#000;margin-left:auto"
            onclick="sendAction({type:'end_turn'})">
      ターン終了
    </button>`;
}

// ── バンド編成名 ──────────────────────────────────────────────────────────
function getBandName(members) {
  const parts = members.flatMap(m => m.part ? m.part.split('/') : []);
  const pc = {};
  parts.forEach(p => { pc[p] = (pc[p] || 0) + 1; });
  const genders = members.map(m => m.gender);
  const allFemale = genders.length > 0 && genders.every(g => g === 'female');
  const allMale   = genders.length > 0 && genders.every(g => g === 'male');
  const n = members.length;
  const names = [];
  if (n === 3 && (pc['Gt']||0) >= 1 && (pc['Ba']||0) >= 1 && (pc['Dr']||0) >= 1) {
    names.push('無もなきスリーピース');
  } else if (n === 4 && (pc['Gt']||0) >= 1 && (pc['Ba']||0) >= 1 && (pc['Dr']||0) >= 1 && (pc['Key']||0) >= 1) {
    names.push('フルバンド');
  } else if (n === 4 && (pc['Gt']||0) >= 2 && (pc['Ba']||0) >= 1 && (pc['Dr']||0) >= 1) {
    names.push('通常バンド');
  }
  if (allFemale) names.push('ガールズバンド');
  else if (allMale) names.push('ボーイズバンド');
  return names.join('・');
}

// ── 対バンモーダル ─────────────────────────────────────────────────────────
function openTaibanModal() {
  const gs = S.gameState;
  const me = gs.players.find(p => p.player_id === S.myPlayerId);
  if (!me || !me.bands?.length) return;

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.style.display = 'flex';

  function renderStep1() {
    overlay.innerHTML = `<div class="modal">
      <h2 style="margin-top:0">🎸 対バン — 自バンドを選択</h2>
      ${me.bands.map(b => {
        const mems = b.members || [];
        const music = mems.reduce((s,m) => s + m.music, 0);
        const names = mems.map(m => esc(m.name)).join('、');
        return `<div class="band-card" style="cursor:pointer;margin-bottom:8px"
                     onclick="window._taibanSelectMy('${b.band_id}')">
          <div class="band-header">
            <span>🎸 ${names}</span>
            <span style="color:#ba68c8">音楽性計 ${music}</span>
          </div>
        </div>`;
      }).join('')}
      <button class="btn btn-sm btn-secondary" style="margin-top:8px"
              onclick="this.closest('.modal-overlay').remove()">キャンセル</button>
    </div>`;
  }

  window._taibanSelectMy = function(myBandId) {
    const opponents = gs.players.filter(p => p.player_id !== S.myPlayerId && p.bands?.length > 0);
    overlay.innerHTML = `<div class="modal">
      <h2 style="margin-top:0">🎸 対バン — 相手バンドを選択</h2>
      ${opponents.map(op => op.bands.map(b => {
        const mems = b.members || [];
        const names = mems.map(m => esc(m.name)).join('、');
        return `<div class="band-card" style="cursor:pointer;margin-bottom:8px"
                     onclick="window._taibanConfirm('${myBandId}','${b.band_id}')">
          <div class="band-header">
            <span>🎸 ${esc(op.name)}: ${names}</span>
            <span style="color:#ba68c8">音楽性 ??</span>
          </div>
        </div>`;
      }).join('')).join('')}
      <button class="btn btn-sm btn-secondary" style="margin-top:8px"
              onclick="window._taibanBack()">戻る</button>
      <button class="btn btn-sm btn-secondary" style="margin-top:8px;margin-left:4px"
              onclick="this.closest('.modal-overlay').remove()">キャンセル</button>
    </div>`;
  };

  window._taibanBack = function() { renderStep1(); };

  window._taibanConfirm = function(myBandId, oppBandId) {
    overlay.remove();
    sendAction({ type: 'taiban', my_band_id: myBandId, opponent_band_id: oppBandId });
  };

  renderStep1();
  document.body.appendChild(overlay);
}

function renderResultScreen(gs) {
  const winner = gs.players.find(p => p.player_id === gs.winner_id);
  const sorted = [...gs.players].sort((a, b) => b.cumulative_mobilization - a.cumulative_mobilization);
  const medals = ['🥇', '🥈', '🥉', '🏅'];
  const rows = sorted.map((p, i) => {
    const isWin = p.player_id === gs.winner_id;
    return `
      <div class="result-row${isWin ? ' result-winner-row' : ''}">
        <span class="result-medal">${medals[i] || ''}</span>
        <span class="result-pname${isWin ? ' result-winner-name' : ''}">${esc(p.name)}</span>
        <span class="result-mob">${p.cumulative_mobilization}</span>
        <span class="result-music">${p.music_score}</span>
      </div>`;
  }).join('');
  return `
    <div class="result-screen">
      <div class="result-trophy">🎉</div>
      <div class="result-headline">${esc(winner?.name ?? '?')} の勝利！</div>
      <div class="result-subtitle">ゲーム終了</div>
      <div class="result-table">
        <div class="result-header">
          <span></span><span>プレイヤー</span><span>動員数</span><span>音楽性</span>
        </div>
        ${rows}
      </div>
      <button class="btn btn-secondary" style="margin-top:24px"
              onclick="location.reload()">ロビーへ戻る</button>
    </div>`;
}

function showStartingPlayerRoulette(gs) {
  const firstPlayer = gs.players[gs.current_player_idx];
  const names = gs.players.map(p => p.name);

  const overlay = document.createElement('div');
  overlay.id = 'starting-roulette';
  overlay.innerHTML = `
    <div class="roulette-inner">
      <div class="roulette-title">先攻決定！</div>
      <div class="roulette-name" id="roulette-spin-name">…</div>
      <div class="roulette-decide" id="roulette-decide"></div>
      <div class="roulette-tap" id="roulette-tap">タップして閉じる</div>
    </div>`;
  document.body.appendChild(overlay);

  const spinEl = overlay.querySelector('#roulette-spin-name');
  const decideEl = overlay.querySelector('#roulette-decide');
  const tapEl = overlay.querySelector('#roulette-tap');

  // 高速スピン → 減速 → 先攻プレイヤーで停止
  const schedule = [];
  let ni = Math.floor(Math.random() * names.length);
  for (let i = 0; i < 20; i++) {
    schedule.push({ name: names[ni++ % names.length], ms: 70 + i * 4 });
  }
  [140, 190, 250, 320, 400, 490].forEach(ms => {
    schedule.push({ name: names[ni++ % names.length], ms });
  });
  schedule.push({ name: firstPlayer.name, ms: 650, final: true });

  let t = 500; // 開幕少し待つ
  for (const s of schedule) {
    t += s.ms;
    const snap = s;
    setTimeout(() => {
      spinEl.textContent = snap.name;
      if (snap.final) {
        spinEl.classList.add('roulette-landed');
        decideEl.textContent = `🎸 ${snap.name} が先攻！`;
        decideEl.classList.add('roulette-decide-show');
        tapEl.classList.add('roulette-tap-show');
        overlay.onclick = () => overlay.remove();
        setTimeout(() => { if (overlay.parentNode) overlay.remove(); }, 7000);
      }
    }, t);
  }
}

function showMyTurnNotification() {
  const existing = document.getElementById('my-turn-notif');
  if (existing) existing.remove();
  const el = document.createElement('div');
  el.id = 'my-turn-notif';
  el.innerHTML = `<div class="my-turn-inner">
    <div class="my-turn-label">🎸 あなたのターンです！</div>
    <div class="my-turn-sub">タップして閉じる</div>
  </div>`;
  el.onclick = () => el.remove();
  document.body.appendChild(el);
  setTimeout(() => { if (el.parentNode) el.remove(); }, 3000);
}

function showActionPopup(events) {
  const existing = document.querySelector('.action-popup');
  if (existing) existing.remove();
  const el = document.createElement('div');
  el.className = 'action-popup';
  el.innerHTML = events.map(e => `<div>${esc(e)}</div>`).join('');
  document.body.appendChild(el);
  clearTimeout(el._t);
  el._t = setTimeout(() => el.remove(), 3800);
}

function showTaibanResultPopup(result) {
  const win = result.result === 'win';
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.style.display = 'flex';
  overlay.innerHTML = `<div class="modal" style="text-align:center">
    <div style="font-size:32px;margin-bottom:8px">${win ? '🏆' : '😔'}</div>
    <h2 style="margin:0 0 12px">${win ? '対バン勝利！' : '対バン敗北…'}</h2>
    <p style="margin:4px 0">音楽性: <strong>${result.my_music}</strong> vs ${result.opp_music}</p>
    ${win ? `<p style="margin:4px 0">動員数 <strong>+${result.steal}</strong> を ${esc(result.loser)} から奪いました！</p>` : `<p style="margin:4px 0">${esc(result.winner)} の勝ち</p>`}
    <p style="color:var(--muted);font-size:12px;margin-top:12px">タップして閉じる</p>
  </div>`;
  overlay.onclick = () => overlay.remove();
  document.body.appendChild(overlay);
}

// ── カードHTML ──────────────────────────────────────────────────────────────
function cardHtml(c, opts = {}) {
  if (!c || typeof c !== 'object') return '';
  if (c.instance_id) _cardCache[c.instance_id] = c;
  const cls = [
    'card',
    opts.large      ? 'card-lg'   : opts.small ? 'card-sm' : '',
    opts.selected   ? 'selected'  : '',
    opts.disabled   ? 'disabled'  : '',
    c.face_down     ? 'face-down' : '',
  ].filter(Boolean).join(' ');
  const onclick = opts.selectable
    ? `onclick="toggleSel('${c.instance_id}')"` : '';
  const hov = c.instance_id
    ? `onmouseenter="onCardEnter(event,'${c.instance_id}')" onmouseleave="onCardLeave()"`
    : '';
  return `<div class="${cls}" ${onclick} ${hov} title="${esc(c.name||'')}">
    ${c.face_down
      ? `<div class="card-name" style="margin:auto;font-size:16px">🂠</div>`
      : cardInner(c, opts)}
  </div>`;
}

function cardInner(c, opts = {}) {
  if (c?.instance_id) _cardCache[c.instance_id] = c;
  const infoBtn = c?.instance_id
    ? `<span class="card-info-btn"
             onclick="event.stopPropagation();showCardDetail(event,'${c.instance_id}')">ℹ</span>`
    : '';
  const imgSrc = memberImagePath(c);
  const imgHtml = imgSrc
    ? `<div class="card-member-img"><img src="${imgSrc}" alt="" loading="lazy" onerror="this.parentNode.style.display='none'"></div>`
    : '';
  const genderMark = c.gender === 'male' ? ' ♂' : c.gender === 'female' ? ' ♀' : '';
  const kindLabel = c.kind === 'member'
    ? `${c.part || ''}${genderMark}`
    : `${_KIND_JA[c.kind]||c.kind}${c.phase ? ' · ' + (_PHASE_JA[c.phase]||c.phase) : ''}`;
  const statsContent = c.kind === 'member'
    ? `<span class="card-stat draw">集${c.draw}</span>
       <span class="card-stat music">音${c.music === -1 ? '??' : c.music}</span>
       <span class="card-stat human">応${c.human}</span>`
    : c.severity != null
      ? `<span class="card-stat" style="color:var(--danger)">事件性 ${c.severity}</span>`
      : `<div class="card-desc-preview">${esc(c.description || effectToJa(c.effect) || '')}</div>`;
  const abilityLine = opts.showAbility && c.ability
    ? `<div class="card-ability-line">⚡${esc(c.ability.name)}: ${esc(effectToJa(c.ability.effect))}</div>`
    : '';
  return `
    ${infoBtn}
    ${imgHtml}
    <div class="card-name">${esc(c.name||'')}</div>
    <div class="card-part">${esc(kindLabel)}</div>
    <div class="card-stats">${statsContent}</div>
    ${abilityLine}`;
}

// ── アクション ─────────────────────────────────────────────────────────────
function toggleSel(id) {
  const i = S.sel.indexOf(id);
  if (i === -1) S.sel.push(id); else S.sel.splice(i, 1);
  render();
}

function onPlayMember() {
  const me = myPlayer();
  const id = S.sel.find(id => me.hand.find(c => c.instance_id === id && c.kind === 'member'));
  if (!id) return;
  sendAction({ type: 'play_member', card_instance_id: id });
  S.sel = [];
}

function onFormBand() {
  const me       = myPlayer();
  const fieldIds = S.sel.filter(id => me.field_members.find(c => c.instance_id === id));
  if (fieldIds.length < 3) { toast('フィールドのメンバーを3人以上選んでください'); return; }
  sendAction({ type: 'form_band', member_instance_ids: fieldIds });
  S.sel = [];
}

function onUseSupport() {
  const me = myPlayer();
  const id = S.sel.find(id => me.hand.find(c => c.instance_id === id && c.kind === 'support'));
  if (!id) return;
  sendAction({ type: 'use_support', card_instance_id: id });
  S.sel = [];
}

function onSetAnti() {
  const me = myPlayer();
  const id = S.sel.find(id => me.hand.find(c => c.instance_id === id && c.kind === 'anti'));
  if (!id) return;
  sendAction({ type: 'set_anti', card_instance_id: id });
  S.sel = [];
}

function revealAnti(instanceId) {
  const gs = S.gameState;
  const opponents = gs.players.filter(p => p.player_id !== S.myPlayerId);
  if (opponents.length === 1) {
    sendAction({ type: 'reveal_anti', card_instance_id: instanceId, target_player_id: opponents[0].player_id });
    return;
  }
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.style.display = 'flex';
  const btns = opponents.map(op =>
    `<button class="btn btn-primary" style="width:100%"
             onclick="this.closest('.modal-overlay').remove();
                      sendAction({type:'reveal_anti',card_instance_id:'${instanceId}',target_player_id:'${op.player_id}'})">
       ${esc(op.name)}
     </button>`
  ).join('');
  overlay.innerHTML = `<div class="modal">
    <h3>🎯 アンチ発動対象を選択</h3>
    ${btns}
    <button class="btn btn-secondary" style="width:100%" onclick="this.closest('.modal-overlay').remove()">キャンセル</button>
  </div>`;
  document.body.appendChild(overlay);
}

// ── カード詳細モーダル ──────────────────────────────────────────────────────

function memberImagePath(c) {
  if (c.kind !== 'member' || !c.part || !c.gender) return null;
  const partKey = c.part.replace('/', '');
  return `/images/members/${partKey}_${c.gender}.png`;
}

const _KIND_JA = { member:'メンバー', support:'サポート', anti:'アンチ', incident:'事件' };
const _PHASE_JA = { action:'アクション時', live:'ライブ前', judgment:'判定前' };

function effectToJa(effect) {
  if (!effect) return '';
  const exact = {
    'draw_card':                'カード1枚ドロー',
    'action+1':                 '行動ポイント+1',
    'performance_record+2':     '活動実績+2',
    'performance_record+4':     '活動実績+4',
    'opponents_record-1':       '相手全員の活動実績-1',
    'opponents_record-3':       '相手全員の活動実績-3',
    'recruit_from_deck':        'デッキからメンバーを1人バンドへ加える',
    'purge_opponent_males':     '相手バンドの男性メンバー1名を除外',
    'draw_per_opponent_female': '相手バンドの女性1人につき集客力+1',
    'free_play_member':         '次のメンバー1枚のコスト0',
    'redraw_hand':              '手札を全て引き直す',
    'encore':                   '最初に成功したバンドが追加ライブ',
    'force_live_success':       'このターンのライブは必ず成功',
    'steal_random_band':        '相手バンドを1つ奪い自フィールドへ',
    'purge_band_females':       '全バンドの女性メンバー2名を学生課送り',
    'zero_music_deck_hand':     '自分のデッキ・手札メンバーの音楽性を0に',
    'poach_random_member':      '相手バンドを解散、メンバー1人を自バンドへ引き抜く',
    'draw2':                    '手札を2枚引く',
    'search_support':           'バンド結成時: デッキからサポート1枚を手札へ',
    'force_success':            'ライブを強制成功させる',
    'rewrite_field_gender_male':'フィールドの全メンバーを男性に書き換え',
    'steal_support':            '相手の手札からサポート1枚を奪う',
    'opponents_discard_random': '相手全員が手札からランダム1枚を捨てる',
  };
  if (exact[effect]) return exact[effect];
  if (effect.startsWith('deal_token:'))
    return `全員の手札に「${effect.split(':')[1]}」を追加`;
  if (effect.startsWith('fail_on_') && effect.endsWith('_self_remove')) {
    const t = effect.slice('fail_on_'.length, -'_self_remove'.length);
    return `「${t}」発生時: ライブ強制失敗＋自身除外`;
  }
  if (effect.startsWith('mobilization_transfer+'))
    return `動員数+${effect.split('+')[1]}`;
  if (effect.startsWith('mobilization+') && effect.endsWith('_once')) {
    const n = effect.split('+')[1].split('_')[0];
    return `初回のみ: 動員数+${n}`;
  }
  if (effect.startsWith('opponents_mobilization-'))
    return `相手全員の動員数-${effect.split('-')[1]}`;
  return effect
    .replace(/success_draw([+-]\d+)/g, '成功時: 集客力$1')
    .replace(/success_music([+-]\d+)/g, '成功時: 音楽性$1')
    .replace(/draw([+-]\d+)/g, '集客力$1')
    .replace(/music([+-]\d+)/g, '音楽性$1')
    .replace(/human([+-]\d+)/g, '対応力$1')
    .replace(/severity([+-]\d+)/g, '事件性$1')
    .replace(/_/g, ' / ');
}

function isAbilityImpl(ab) {
  if (!ab) return true;
  const key = `${ab.type}:${ab.hook}`;
  return key === 'static:on_band_stat' ||
         key === 'on_play:on_play'     ||
         key === 'on_play:on_form'     ||
         key === 'on_form:on_form'     ||
         key === 'judgment:on_judgment';
}

function showCardDetail(ev, instanceId) {
  ev && ev.stopPropagation();
  const c = _cardCache[instanceId];
  if (!c) return;
  onCardLeave();
  closeCardDetail();

  const statsHtml = (() => {
    if (c.kind === 'member') {
      return `<div class="cdd-stats">
        <span style="color:#64b5f6">集客&nbsp;<b>${c.draw}</b></span>
        <span style="color:#ba68c8">音楽&nbsp;<b>${c.music === -1 ? '??' : c.music}</b></span>
        <span style="color:#ff6060">対応力&nbsp;<b>${c.human}</b></span>
      </div>`;
    }
    if (c.severity != null) {
      return `<div style="color:var(--danger)">事件性&nbsp;<b>${c.severity}</b></div>`;
    }
    const descText = c.description || c.effect || '';
    if (descText) {
      return `<div style="color:var(--muted);font-size:12px">${esc(descText)}</div>`;
    }
    return '';
  })();

  const abilHtml = (() => {
    if (!c.ability) return c.kind === 'member' ? '<div style="color:var(--muted);font-size:12px">能力なし</div>' : '';
    const impl = isAbilityImpl(c.ability);
    return `<div class="cdd-ability">
      <div class="cdd-ability-name">【${esc(c.ability.name)}】</div>
      <div>${esc(effectToJa(c.ability.effect))}</div>
      ${!impl ? '<div class="cdd-unimpl">⚠ 現在未対応（M4実装予定）</div>' : ''}
    </div>`;
  })();

  const overlay = document.createElement('div');
  overlay.id = 'cdd-overlay';
  overlay.className = 'modal-overlay';
  overlay.onclick = closeCardDetail;
  overlay.innerHTML = `
    <div class="modal" onclick="event.stopPropagation()">
      <div style="font-size:17px;font-weight:bold;color:var(--accent)">${esc(c.name||'？')}</div>
      <div style="font-size:12px;color:var(--muted)">
        ${c.part ? esc(c.part) + ' · ' : ''}${esc(_KIND_JA[c.kind]||c.kind)}
      </div>
      ${statsHtml}
      ${abilHtml}
      <button class="btn btn-secondary btn-sm" onclick="closeCardDetail()">閉じる</button>
    </div>`;
  document.body.appendChild(overlay);
}

function closeCardDetail() {
  document.getElementById('cdd-overlay')?.remove();
}

// ── PC ホバーパネル ──────────────────────────────────────────────────────────

let _hoverTimer = null;

function onCardEnter(ev, instanceId) {
  if (!matchMedia('(hover: hover)').matches) return;
  clearTimeout(_hoverTimer);
  _hoverTimer = setTimeout(() => {
    const c = _cardCache[instanceId];
    if (!c) return;

    let panel = document.getElementById('card-hover-panel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'card-hover-panel';
      panel.className = 'card-hover-panel';
      document.body.appendChild(panel);
    }

    const statsLine = c.kind === 'member'
      ? `集${c.draw}&nbsp;/&nbsp;音${c.music === -1 ? '??' : c.music}&nbsp;/&nbsp;応<span style="color:#ff6060;font-weight:bold">${c.human}</span>`
      : c.severity != null ? `事件性: ${c.severity}` : '';

    const abilLine = (() => {
      if (!c.ability) {
        if (c.kind === 'member') return '能力なし';
        return esc(c.description || c.effect || '');
      }
      const impl = isAbilityImpl(c.ability);
      return `<span style="color:var(--accent)">${esc(c.ability.name)}</span>: ${esc(effectToJa(c.ability.effect))}`
        + (!impl ? '&nbsp;<span style="color:var(--warn)">⚠未対応</span>' : '');
    })();

    panel.innerHTML = `<b>${esc(c.name||'')}</b>${c.part ? `&nbsp;<span style="color:var(--muted)">${esc(c.part)}</span>` : ''}<br>`
      + (statsLine ? statsLine + '<br>' : '')
      + abilLine;

    const card = ev.currentTarget;
    const rect = card.getBoundingClientRect();
    const x = Math.min(rect.right + 8, window.innerWidth - 230);
    const y = Math.max(8, rect.top - 10);
    panel.style.left = x + 'px';
    panel.style.top  = y + 'px';
    panel.style.display = 'block';
  }, 250);
}

function onCardLeave() {
  clearTimeout(_hoverTimer);
  const panel = document.getElementById('card-hover-panel');
  if (panel) panel.style.display = 'none';
}

// ── ライブ演出 ─────────────────────────────────────────────────────────────

function startLivePresentation(prevGs, newState) {
  const results = newState.last_live_results;
  if (!results?.length) return false;

  const activePid = prevGs?.players?.[prevGs.current_player_idx]?.player_id;
  clearTimeout(LP.autoTimer);
  Object.assign(LP, {
    active: true,
    bandResults: results,
    bandIdx: 0,
    step: 0,
    postState: newState,
    isActiveLivePlayer: activePid === S.myPlayerId,
  });
  S.screen = 'live_pres';
  return true;
}

function renderLivePres() {
  const res   = LP.bandResults[LP.bandIdx];
  const cur   = LP.bandIdx + 1;
  const total = LP.bandResults.length;
  if (!res) { lpEnd(); return; }

  if (LP.step === 0) lpStep0(res, cur, total);
  else if (LP.step === 1) lpStep1(res, cur, total);
  else if (LP.step === 2) lpStep2(res, cur, total);
  else                    lpStep3(res, cur, total);

  if (!LP.isActiveLivePlayer) {
    clearTimeout(LP.autoTimer);
    LP.autoTimer = setTimeout(lpAdvance, 30000); // sync via lp_sync; fallback for disconnects
  }
}

function _lpObserverNote() {
  return LP.isActiveLivePlayer ? '' :
    '<div class="lp-observer-note">⏳ 相手がライブ処理中…（自動で進みます）</div>';
}

function _lpToolbar(showBack = false, nextLabel = '次へ →') {
  if (!LP.isActiveLivePlayer) return;
  const tb = $('actions-toolbar');
  tb.style.display = 'flex';
  tb.innerHTML = (showBack
    ? `<button class="btn btn-secondary btn-sm" onclick="lpBack()">← 戻る</button>` : '')
    + `<button class="btn btn-primary" style="flex:1;font-size:15px;padding:13px"
               onclick="lpAdvance()">${nextLabel}</button>`;
}

function lpStep0(res, cur, total) {
  const memCards = res.members.map(m => cardHtml(m)).join('');
  const names    = res.members.map(m => m.name).join(' / ');

  $('main-content').innerHTML = `
    <div class="live-pres">
      <div class="lp-header"><span class="lp-step-label">ステップ 1/4 — ライブ開始</span></div>
      <div class="lp-band-title">🎸 バンド ${cur}/${total}</div>
      <div>
        <div class="section-title" style="text-align:center;margin-bottom:8px">${esc(names)}</div>
        <div class="cards-row" style="justify-content:center">${memCards}</div>
      </div>
      <div class="lp-stats">
        <div class="lp-stat">
          <span style="color:#64b5f6;font-size:26px;font-weight:bold">${res.draw_total}</span>
          <span>集客</span>
        </div>
        <div class="lp-stat">
          <span style="color:#ba68c8;font-size:26px;font-weight:bold">${res.music_total}</span>
          <span>音楽</span>
        </div>
        <div class="lp-stat">
          <span style="color:#ff6060;font-size:26px;font-weight:bold">${res.human_total}</span>
          <span>対応力</span>
        </div>
      </div>
      ${_lpObserverNote()}
    </div>`;
  _lpToolbar(false, 'ライブ実行 →');
}

function lpStep1(res, cur, total) {
  $('main-content').innerHTML = `
    <div class="live-pres">
      <div class="lp-header"><span class="lp-step-label">ステップ 2/4 — 集計・判定値</span></div>
      <div class="lp-band-title">🎸 バンド ${cur}/${total}</div>

      <div class="lp-section">
        <div class="lp-section-title">📊 ライブ見込み（成功した場合）</div>
        <div class="lp-gain-row">
          <span>動員数</span><span class="lp-gain">+${res.draw_total}</span>
        </div>
        <div class="lp-gain-row">
          <span>音楽性</span><span class="lp-gain">+${res.music_total}</span>
        </div>
        <div class="lp-gain-row">
          <span>活動実績</span><span class="lp-gain">+1</span>
        </div>
      </div>

      <div class="lp-section">
        <div class="lp-section-title">⚖️ 対応力（引いた事件性以上なら成功）</div>
        <div class="lp-jv-formula">
          このバンドの対応力合計&nbsp;=&nbsp;<span class="lp-jv-val">${res.judgment_value}</span>
        </div>
        <div class="lp-hint">事件性 ≤ 対応力 → ライブ成功 / 事件性 ＞ 対応力 → 学生課送り</div>
      </div>
      ${_lpObserverNote()}
    </div>`;
  _lpToolbar(true, '事件カードを引く →');
}

function lpStep2(res, cur, total) {
  const hasJudgEvents = res.judgment_events && res.judgment_events.length > 0;
  const sevChanged = res.raw_severity !== undefined && res.raw_severity !== res.incident_severity;
  const sevDisplay = sevChanged
    ? `<s style="opacity:0.5">${res.raw_severity}</s> → ${res.incident_severity}`
    : res.incident_severity;
  const judgeEventsHtml = hasJudgEvents
    ? `<div class="ability-events" id="lp-ability-events" style="opacity:0;transition:opacity 0.5s">
         ${res.judgment_events.map(e => `<div class="ability-badge">⚡ ${esc(e)}</div>`).join('')}
       </div>`
    : '';

  $('main-content').innerHTML = `
    <div class="live-pres">
      <div class="lp-header"><span class="lp-step-label">ステップ 3/4 — 事件めくり</span></div>
      <div class="lp-band-title">🎸 バンド ${cur}/${total}</div>
      <div class="incident-flip">
        <div class="flip-card">
          <div class="flip-card-inner" id="lp-flip-inner">
            <div class="flip-card-back">🃏</div>
            <div class="flip-card-front">
              <div class="inc-name">「${esc(res.incident_name)}」</div>
              <div class="inc-sev">事件性: ${sevDisplay}</div>
            </div>
          </div>
        </div>
      </div>
      ${judgeEventsHtml}
      ${_lpObserverNote()}
    </div>`;
  setTimeout(() => {
    const inner = document.getElementById('lp-flip-inner');
    if (inner) inner.classList.add('flipped');
  }, 700);
  if (hasJudgEvents) {
    setTimeout(() => {
      const el = document.getElementById('lp-ability-events');
      if (el) el.style.opacity = '1';
    }, 1400);
  }
  _lpToolbar(true, '判定へ →');
}

function lpStep3(res, cur, total) {
  const isLast = LP.bandIdx >= LP.bandResults.length - 1;
  const nextLabel = isLast && !res.success ? '学生課送り指名へ →'
                  : isLast                 ? 'ターン終了'
                  :                          '次のバンドへ →';
  const cmp = res.judgment_value >= res.incident_severity;

  const sevChanged = res.raw_severity !== undefined && res.raw_severity !== res.incident_severity;
  const sevHtml = sevChanged
    ? `<s style="opacity:0.45;color:var(--muted)">${res.raw_severity}</s>&nbsp;<b style="font-size:20px">${res.incident_severity}</b>`
    : `<b style="font-size:20px">${res.incident_severity}</b>`;

  const hasJudgEvents = res.judgment_events && res.judgment_events.length > 0;
  const judgeEventsHtml = hasJudgEvents
    ? `<div class="ability-events">
         ${res.judgment_events.map(e => `<div class="ability-badge">⚡ ${esc(e)}</div>`).join('')}
       </div>`
    : '';

  const resultHtml = res.success
    ? `<div style="color:var(--success);font-size:22px;font-weight:bold;text-align:center;margin:8px 0">
         ✅ ライブ成功！
       </div>
       <div class="lp-section">
         <div class="lp-gain-row"><span>動員数</span><span class="lp-gain">+${res.mobilization_gain}</span></div>
         <div class="lp-gain-row"><span>音楽性</span><span class="lp-gain">+${res.music_gain}</span></div>
         <div class="lp-gain-row"><span>活動実績</span><span class="lp-gain">+1</span></div>
       </div>`
    : `<div style="color:var(--danger);font-size:22px;font-weight:bold;text-align:center;margin:8px 0">
         ⚡ 事件発生！
       </div>
       <div class="lp-section" style="border:1px solid var(--danger)">
         <div style="text-align:center;font-size:15px">「${esc(res.incident_name)}」</div>
         <div class="lp-hint">学生課送り指名フローへ</div>
       </div>`;

  $('main-content').innerHTML = `
    <div class="live-pres">
      <div class="lp-header"><span class="lp-step-label">ステップ 4/4 — 判定結果</span></div>
      <div class="lp-band-title">🎸 バンド ${cur}/${total}</div>
      <div class="lp-section" style="text-align:center;font-size:15px">
        対応力&nbsp;<b style="font-size:20px">${res.judgment_value}</b>
        &nbsp;${cmp ? '&ge;' : '&lt;'}&nbsp;
        事件性&nbsp;${sevHtml}
        &nbsp;&nbsp;→&nbsp;&nbsp;<b>${cmp ? '成功' : '事件'}</b>
      </div>
      ${judgeEventsHtml}
      ${resultHtml}
      ${_lpObserverNote()}
    </div>`;
  _lpToolbar(true, nextLabel);
}

function _lpSyncSend(kind, bandIdx, step) {
  if (S.mode === 'online' && LP.isActiveLivePlayer && S.ws?.readyState === WebSocket.OPEN) {
    S.ws.send(JSON.stringify({ type: 'lp_sync', kind, band_idx: bandIdx, step }));
  }
}

function lpAdvance() {
  clearTimeout(LP.autoTimer);
  LP.step++;
  if (LP.step > 3) {
    LP.bandIdx++;
    LP.step = 0;
    if (LP.bandIdx >= LP.bandResults.length) {
      _lpSyncSend('end', 0, 0);
      lpEnd();
      return;
    }
  }
  _lpSyncSend('step', LP.bandIdx, LP.step);
  renderLivePres();
}

function lpBack() {
  clearTimeout(LP.autoTimer);
  if (LP.step > 0) LP.step--;
  _lpSyncSend('step', LP.bandIdx, LP.step);
  renderLivePres();
}

function lpEnd() {
  clearTimeout(LP.autoTimer);
  LP.active = false;
  const gs = LP.postState;
  S.gameState = gs;
  if (S.mode === 'hotseat') {
    hotseatTransition(gs);
  } else {
    onlineTransition(gs);
  }
  render();
}

// ── WebSocket ──────────────────────────────────────────────────────────────
function connectWs() {
  if (!S.roomCode || !S.myName) return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws    = new WebSocket(
    `${proto}://${location.host}/ws/${S.roomCode}/${encodeURIComponent(S.myName)}`
  );
  S.ws = ws;

  ws.onopen = () => {
    if (S.screen === 'connecting') {
      // 接続完了したが state 受信待ち — サーバーが即座に送ってくれる
    }
  };

  ws.onmessage = ev => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }

    if (msg.type === 'error') {
      toast('⚠ ' + msg.message, 4000);
      return;
    }

    if (msg.type === 'room') {
      // ゲーム開始前の待機室情報
      S.gameState = { players: msg.players };
      if (S.screen !== 'waiting') S.screen = 'waiting';
      render();
      return;
    }

    if (msg.type === 'lp_sync') {
      if (LP.active) {
        clearTimeout(LP.autoTimer);
        if (msg.kind === 'end') {
          lpEnd();
        } else {
          LP.bandIdx = msg.band_idx;
          LP.step    = msg.step;
          renderLivePres();
        }
      }
      return;
    }

    if (msg.type === 'state') {
      onStateUpdate(msg.state);
    }
  };

  ws.onerror = () => toast('接続エラーが発生しました');

  ws.onclose = () => {
    if (S.mode === 'online' && S.screen !== 'lobby') {
      toast('接続が切れました。再接続中…', 3000);
      setTimeout(connectWs, 3000);
    }
    // ホットシートは明示的に reconnectWs() が呼ぶので自動再接続しない
  };
}

function reconnectWs() {
  if (S.ws) {
    S.ws.onclose = null; // 自動再接続を抑止
    S.ws.close();
    S.ws = null;
  }
  connectWs();
}

// ── 状態更新ハンドラ ────────────────────────────────────────────────────────
function onStateUpdate(gs) {
  const prevGs = S.gameState;
  S.gameState = gs;

  const me = gs.players?.find(p => p.name === S.myName);
  if (me) S.myPlayerId = me.player_id;

  // BGM 切り替え
  if (['mulligan', 'action', 'live_processing'].includes(gs.phase)) {
    bgmPlay('game');
  } else if (gs.phase === 'game_over') {
    bgmStop();
  }

  // LP演出が進行中に次の更新が来た場合はpostStateだけ更新して待機
  if (LP.active) {
    LP.postState = gs;
    return;
  }

  // ライブ結果（構造化）を検出 → 演出開始
  // prevGs にすでに結果があるケース（reconnectWs後の再送など）は再発火しない
  const prevHadResults = prevGs?.last_live_results?.length > 0;
  if (prevGs && !prevHadResults && gs.last_live_results?.length > 0) {
    if (startLivePresentation(prevGs, gs)) {
      render();
      return;
    }
  }

  if (gs.taiban_result) {
    showTaibanResultPopup(gs.taiban_result);
  }

  // ゲーム開始時の先攻決定ルーレット（イベントログが1件＝開始直後のみ）
  if (!prevGs && gs.phase === 'mulligan' && gs.event_log?.length === 1) {
    showStartingPlayerRoulette(gs);
  }

  // 自分のターンになった瞬間を検出して通知
  const prevIsMyTurn = prevGs?.phase === 'action'
    && prevGs?.players?.[prevGs?.current_player_idx]?.player_id === S.myPlayerId;
  const nowIsMyTurn = gs.phase === 'action'
    && gs.players?.[gs.current_player_idx]?.player_id === S.myPlayerId;
  if (!prevIsMyTurn && nowIsMyTurn) {
    showMyTurnNotification();
  }

  // アクションポップアップ（全プレイヤーに表示）
  const evLen = (gs.event_log || []).length;
  if (gs.last_action_events?.length > 0 && evLen !== (S.lastPopupLogLen || 0)) {
    S.lastPopupLogLen = evLen;
    showActionPopup(gs.last_action_events);
  }

  if (S.mode === 'hotseat') {
    hotseatTransition(gs);
  } else {
    onlineTransition(gs);
  }
  render();
}

/** ホットシート: 誰が次に操作すべきか判断してハンドオフを挟む */
function hotseatTransition(gs) {
  if (gs.phase === 'game_over') { S.screen = 'game'; return; }

  const needed = neededPlayer(gs);
  if (needed && needed.player_id !== S.myPlayerId) {
    // 別のプレイヤーが必要 → ハンドオフ
    S.handoffTarget = needed.name;
    S.screen = 'handoff';
  } else {
    // 自分が操作する
    switch (gs.phase) {
      case 'mulligan':        S.screen = 'mulligan'; break;
      case 'live_processing': S.screen = 'game';     break;
      default:                S.screen = 'game';     break;
    }
  }
}

/** オンライン: 画面遷移はシンプル */
function onlineTransition(gs) {
  if (gs.phase === 'mulligan') {
    S.screen = 'mulligan';
  } else {
    S.screen = 'game';
  }
}

/**
 * そのフェーズで「次に行動すべきプレイヤー」を返す。
 * null のときはサーバーが自動処理中。
 */
function neededPlayer(gs) {
  switch (gs.phase) {
    case 'mulligan':
      return gs.players.find(p => !p.mulligan_done) || null;
    case 'action':
      return gs.players[gs.current_player_idx] || null;
    case 'sotai':
      return gs.players.find(p => p.player_id === gs.sotai_context?.nominator_player_id) || null;
    default:
      return gs.players[gs.current_player_idx] || null;
  }
}

// ── WebSocket アクション送信 ───────────────────────────────────────────────
function sendAction(action) {
  if (!S.ws || S.ws.readyState !== WebSocket.OPEN) {
    toast('サーバーに接続されていません');
    return;
  }
  S.ws.send(JSON.stringify(action));
  S.sel = []; // 送信後は選択をリセット
}

// ── REST ───────────────────────────────────────────────────────────────────
function api(method, path, body) {
  return fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body != null ? JSON.stringify(body) : undefined,
  });
}

// ── UI ユーティリティ ──────────────────────────────────────────────────────
function toast(msg, ms = 2500) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('show'), ms);
}

function phaseLabel(phase) {
  return {
    lobby:           'ロビー',
    mulligan:        'マリガン',
    action:          'アクション',
    live_processing: 'ライブ処理中…',
    sotai:           '学生課送り指名',
    game_over:       'ゲーム終了',
  }[phase] || phase;
}

function myPlayer() {
  return S.gameState?.players?.find(p => p.player_id === S.myPlayerId)
    || { hand: [], field_members: [], bands: [], anti_zone: [] };
}

// ── PWA ────────────────────────────────────────────────────────────────────
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/service-worker.js').catch(() => {});
}

// ── 起動 ────────────────────────────────────────────────────────────────────
render();
