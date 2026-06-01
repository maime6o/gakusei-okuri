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
  pt.textContent = phaseLabel(gs.phase) + (isMyTurn ? ` 残${gs.actions_remaining}手` : '');
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
    <div class="lobby-wrap">
      <h2>🎸 ほーろっくよーがっく2026</h2>
      <div style="font-size:12px;color:var(--muted);margin-top:-8px;margin-bottom:4px;text-align:center">目指せ最高のライブ</div>

      <div class="lobby-title-img-wrap">
        <img class="lobby-title-img" src="/images/title.png" alt=""
             onerror="this.parentNode.style.display='none'">
      </div>

      <div class="card-section">
        <h3>📖 説明書</h3>
        <div class="rulebook">
          <h4>🏆 勝利条件</h4>
          目標動員数（デフォルト120）に先に到達したプレイヤーの勝利。
          <h4>🔄 ターンの流れ</h4>
          行動ポイント3を使い、ドロー・メンバーをフィールドに出す・バンド結成を行う。ターン終了でライブ判定へ。
          <h4>🎸 バンド結成</h4>
          フィールドのメンバー3人以上を選んでバンドを組む。
          <h4>⚡ ライブ判定</h4>
          事件カードを1枚引き、バンドの対応力合計 ≥ 事件性なら成功。成功すると動員数・音楽性を獲得。失敗するとメンバー1名が学生課送り。
          <h4>🃏 サポート / アンチ</h4>
          サポートカードは自分のターンに使う補助効果。アンチカードは事前にセットしておくと相手のライブ時に自動発動。
        </div>
      </div>

      <div class="card-section">
        <h3>🎮 このデバイスで全員プレイ（ホットシート）</h3>
        <p style="color:var(--muted);font-size:12px">1台を順番に回して遊びます。</p>
        <button class="btn btn-primary" onclick="S.screen='hotseat_setup';render()">
          ホットシートで始める
        </button>
      </div>
      <div class="card-section">
        <h3>📱 各自の端末で遊ぶ（オンライン）</h3>
        <label>あなたの名前</label>
        <input id="create-name" type="text" placeholder="例: Alice" maxlength="12">
        <label>目標動員数</label>
        <select id="create-target">
          <option value="80">80（短め）</option>
          <option value="120" selected>120（標準）</option>
          <option value="160">160（長め）</option>
        </select>
        <button class="btn btn-primary" onclick="onCreateOnline()">部屋を作る</button>
        <hr style="border-color:var(--accent2);margin:8px 0">
        <label>あなたの名前</label>
        <input id="join-name" type="text" placeholder="例: Bob" maxlength="12">
        <label>部屋コード（5文字）</label>
        <input id="join-code" type="text" placeholder="ABCDE" maxlength="5"
               style="text-transform:uppercase;letter-spacing:4px;font-size:18px;text-align:center">
        <button class="btn btn-secondary" onclick="onJoinOnline()">コードで参加</button>
      </div>
      <div id="lobby-error" class="error-banner"></div>
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

  // Waiting for someone else
  if (me.mulligan_done) {
    const waiting = gs.players.filter(p => !p.mulligan_done).map(p => p.name).join('、');
    $('main-content').innerHTML = `
      <div class="lobby-wrap" style="text-align:center">
        <p style="padding:20px 0">マリガン済み ✓</p>
        <p style="color:var(--muted)">待機中: ${esc(waiting)}</p>
      </div>`;
    return;
  }

  $('main-content').innerHTML = `
    <div class="lobby-wrap">
      <h2>${esc(me.name)} のマリガン</h2>
      <div class="card-section">
        <h3>初期手札（5枚）</h3>
        <div class="cards-row">${me.hand.map(c => cardHtml(c)).join('')}</div>
      </div>
      <div class="card-section">
        <p>この手札を使いますか？<br>
           <small style="color:var(--muted)">「引き直し」は手札を全て戻して5枚引き直します（1回限り）</small>
        </p>
        <div style="display:flex;gap:8px;margin-top:8px">
          <button class="btn btn-primary" style="flex:1"
                  onclick="sendAction({type:'mulligan',keep:true})">キープ</button>
          <button class="btn btn-secondary" style="flex:1"
                  onclick="sendAction({type:'mulligan',keep:false})">引き直し</button>
        </div>
      </div>
    </div>`;
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

  let html = '<div class="board">';

  // ── 勝利 ──
  if (gs.phase === 'game_over') {
    const winner = gs.players.find(p => p.player_id === gs.winner_id);
    html += `
      <div style="text-align:center;padding:40px 20px">
        <div style="font-size:48px;margin-bottom:12px">🎉</div>
        <div style="font-size:26px;color:var(--accent);margin-bottom:8px">
          ${esc(winner?.name ?? '?')} の勝利！
        </div>
        <button class="btn btn-secondary" style="margin-top:20px"
                onclick="location.reload()">ロビーへ戻る</button>
      </div>`;
    $('main-content').innerHTML = html + '</div>';
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

  if (!me) { $('main-content').innerHTML = html + '</div>'; return; }

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
          selectable: isMyTurn,
          selected:   S.sel.includes(c.instance_id),
          disabled:   c.kind === 'member' && c.music > me.performance_record,
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
      html += `
        <div class="band-card">
          <div class="band-header">
            <span style="font-size:12px">🎸 バンド（${mems.length}人）</span>
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

  // ── 他プレイヤーサマリー ──
  for (const op of gs.players) {
    if (op.player_id === S.myPlayerId) continue;
    const handCount  = typeof op.hand === 'object' && !Array.isArray(op.hand)
                         ? op.hand.count : (op.hand?.length ?? 0);
    const isOpActive = op.player_id === cp?.player_id;
    html += `
      <div class="card-section" style="padding:8px 12px;${isOpActive?'border-color:var(--accent)':''}">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>${esc(op.name)}${isOpActive?' ◀ 手番':''}</span>
          <span style="color:var(--muted);font-size:11px">
            手札:${handCount}枚 バンド:${op.bands?.length??0} 活動実績:${op.performance_record}
          </span>
        </div>
        ${(op.bands?.length??0) > 0 ? `
          <div class="bands-section" style="margin-top:6px">
            ${(op.bands||[]).map(b => {
              const ms = b.members||[];
              return `<div class="band-card" style="padding:6px 8px">
                <div style="font-size:11px;color:var(--muted)">
                  ${ms.map(m=>esc(m.name)).join(' / ')}
                  — 集${b.live_draw||ms.reduce((s,m)=>s+m.draw,0)}
                    音${b.live_music||ms.reduce((s,m)=>s+m.music,0)}
                    応${b.live_human||ms.reduce((s,m)=>s+m.human,0)}
                </div>
              </div>`;
            }).join('')}
          </div>` : ''}
      </div>`;
  }

  // ── イベントログ ──
  const log = (gs.event_log || []).slice(-40).reverse();
  html += `
    <div class="log-panel">
      ${log.map(l => `<div class="log-entry">${esc(l)}</div>`).join('')}
    </div>`;

  html += '</div>';
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

  tb.innerHTML = `
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
    <button class="btn btn-sm" style="background:var(--warn);color:#000;margin-left:auto"
            onclick="sendAction({type:'end_turn'})">
      ターン終了
    </button>`;
}

// ── カードHTML ──────────────────────────────────────────────────────────────
function cardHtml(c, opts = {}) {
  if (!c || typeof c !== 'object') return '';
  if (c.instance_id) _cardCache[c.instance_id] = c;
  const cls = [
    'card',
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
      : cardInner(c)}
  </div>`;
}

function cardInner(c) {
  if (c?.instance_id) _cardCache[c.instance_id] = c;
  const infoBtn = c?.instance_id
    ? `<span class="card-info-btn"
             onclick="event.stopPropagation();showCardDetail(event,'${c.instance_id}')">ℹ</span>`
    : '';
  const imgSrc = memberImagePath(c);
  const imgHtml = imgSrc
    ? `<div class="card-member-img"><img src="${imgSrc}" alt="" loading="lazy" onerror="this.parentNode.style.display='none'"></div>`
    : '';
  return `
    ${infoBtn}
    ${imgHtml}
    <div class="card-name">${esc(c.name||'')}</div>
    <div class="card-part">${esc(c.part||c.kind||'')}</div>
    <div class="card-stats">
      ${c.kind === 'member'
        ? `<span class="card-stat draw">集${c.draw}</span>
           <span class="card-stat music">音${c.music}</span>
           <span class="card-stat human">応${c.human}</span>`
        : `<span class="card-stat" style="font-size:8px">${esc(c.phase||c.effect||'')}</span>`}
    </div>`;
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
  sendAction({ type: 'reveal_anti', card_instance_id: instanceId });
}

// ── カード詳細モーダル ──────────────────────────────────────────────────────

function memberImagePath(c) {
  if (c.kind !== 'member' || !c.part || !c.gender) return null;
  const partKey = c.part.replace('/', '');
  return `/images/members/${partKey}_${c.gender}.png`;
}

function effectToJa(effect) {
  if (!effect) return '';
  return effect
    .replace(/success_draw([+-]\d+)/g, '成功時: 集客力$1')
    .replace(/success_music([+-]\d+)/g, '成功時: 音楽性$1')
    .replace(/draw([+-]\d+)/g, '集客力$1')
    .replace(/music([+-]\d+)/g, '音楽性$1')
    .replace(/human([+-]\d+)/g, '対応力$1')
    .replace(/severity([+-]\d+)/g, '事件性$1')
    .replace(/action\+1/g, '行動ポイント+1')
    .replace(/draw_card/g, 'カード1枚ドロー')
    .replace(/_/g, ' / ');
}

function isAbilityImpl(ab) {
  if (!ab) return true;
  const key = `${ab.type}:${ab.hook}`;
  return key === 'static:on_band_stat' ||
         key === 'on_play:on_play'     ||
         key === 'on_play:on_form'     ||
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
        <span style="color:#ba68c8">音楽&nbsp;<b>${c.music}</b></span>
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
        ${c.part ? esc(c.part) + ' · ' : ''}${esc(c.kind)}
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
      ? `集${c.draw}&nbsp;/&nbsp;音${c.music}&nbsp;/&nbsp;応<span style="color:#ff6060;font-weight:bold">${c.human}</span>`
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
    LP.autoTimer = setTimeout(lpAdvance, 5000);
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
              <div class="inc-sev">事件性: ${res.incident_severity}</div>
            </div>
          </div>
        </div>
      </div>
      ${_lpObserverNote()}
    </div>`;
  setTimeout(() => {
    const inner = document.getElementById('lp-flip-inner');
    if (inner) inner.classList.add('flipped');
  }, 700);
  _lpToolbar(true, '判定へ →');
}

function lpStep3(res, cur, total) {
  const isLast = LP.bandIdx >= LP.bandResults.length - 1;
  const nextLabel = isLast && !res.success ? '学生課送り指名へ →'
                  : isLast                 ? 'ターン終了'
                  :                          '次のバンドへ →';
  const cmp = res.judgment_value >= res.incident_severity; // true = success

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
        事件性&nbsp;<b style="font-size:20px">${res.incident_severity}</b>
        &nbsp;&nbsp;→&nbsp;&nbsp;<b>${cmp ? '成功' : '事件'}</b>
      </div>
      ${resultHtml}
      ${_lpObserverNote()}
    </div>`;
  _lpToolbar(true, nextLabel);
}

function lpAdvance() {
  clearTimeout(LP.autoTimer);
  LP.step++;
  if (LP.step > 3) {
    LP.bandIdx++;
    LP.step = 0;
    if (LP.bandIdx >= LP.bandResults.length) { lpEnd(); return; }
  }
  renderLivePres();
}

function lpBack() {
  clearTimeout(LP.autoTimer);
  if (LP.step > 0) LP.step--;
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
