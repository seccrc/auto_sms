function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

const ICON_PENCIL = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
const ICON_CHECK = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';

// 휴대폰과 연결 알림에서 읽어온 msg_time은 "오후 9:26"/"어제" 같은 상대 표기라
// 행마다 형식이 제각각이었다. created_at은 항상 "YYYY-MM-DD HH:MM:SS"로 저장돼
// 있으므로 이걸 우선 써서 "YYYY-MM-DD HH:MM"로 통일해 보여준다.
function formatDateTime(m) {
    const s = (m && (m.created_at || m.msg_time)) || '';
    const match = s.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
    return match ? `${match[1]} ${match[2]}` : s;
}

let templatesCache = [];
const STATUS_OPTIONS = ['접수', '부서전달', '담당자확인', '처리완료'];
const MANUAL_INPUT_OPTIONS = ['', '행정종합관찰제', '종합민원이력시스템'];

// ── 알림(토스트) / 확인창 ──
// 브라우저 기본 alert/confirm은 화면을 가리고 투박해서, 저장·발송 결과는
// 잠깐 떴다 사라지는 토스트로, 되돌릴 수 없는 작업의 확인은 화면 안
// 대화상자로 바꿨다.
function showToast(message, kind = '') {
    const area = document.getElementById('toastArea');
    const el = document.createElement('div');
    el.className = 'toast' + (kind ? ` is-${kind}` : '');
    el.textContent = message;
    area.appendChild(el);
    setTimeout(() => el.remove(), kind === 'bad' ? 4500 : 2500);
}

// confirm()과 달리 Promise를 돌려주므로 호출부에서 await로 쓴다.
function confirmDialog(title, message, confirmLabel = '확인', danger = true) {
    return new Promise(resolve => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
            <div class="modal-box">
                <h3>${esc(title)}</h3>
                <p>${esc(message)}</p>
                <div class="modal-actions">
                    <button class="btn-ghost" data-act="cancel">취소</button>
                    <button class="${danger ? 'btn-danger' : 'btn-primary'}" data-act="ok">${esc(confirmLabel)}</button>
                </div>
            </div>`;
        const close = (result) => { overlay.remove(); document.removeEventListener('keydown', onKey); resolve(result); };
        const onKey = (e) => { if (e.key === 'Escape') close(false); };
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) close(false);
            const act = e.target.closest('[data-act]');
            if (act) close(act.dataset.act === 'ok');
        });
        document.addEventListener('keydown', onKey);
        document.body.appendChild(overlay);
        overlay.querySelector('[data-act="ok"]').focus();
    });
}

// lastThreads는 15초 주기 폴링에만 갱신되므로, 저장 직후 사용자가 수정
// 모드를 빠져나가 renderThreads()가 다시 그리면 방금 저장한 값이 아니라
// 이 캐시에 남은 옛 값으로 되돌아가 보이는 문제가 있었다. 저장에 성공하면
// 캐시도 같이 갱신해서 폴링을 기다리지 않고 바로 반영되게 한다.
function findComplaintById(id) {
    const t = lastThreads.find(t => t.complaint.id === id);
    return t ? t.complaint : null;
}

async function updateMessageStatus(id, status) {
    try {
        const r = await fetch(`/api/messages/${id}/status`, {
            method: 'PATCH', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({status})
        });
        if (r.ok) {
            const c = findComplaintById(id);
            if (c) c.status = status;
            renderThreads();
        }
    } catch (e) {}
}

// ── 상용문구 ──
const TEMPLATES_COLLAPSED_COUNT = 3;  // 왼쪽 레일이 좁아서 기본은 3개만 보여주고 "더보기"로 펼친다
let templatesExpanded = false;

async function loadTemplates() {
    const listEl = document.getElementById('templateList');
    try {
        const r = await fetch('/api/templates');
        const d = await r.json();
        templatesCache = d.templates || [];
        renderTemplateList();
        renderThreads(); // 상용문구 목록이 새로 로드되면 답신 상자의 문구 드롭다운도 갱신
        renderAutoReplyTemplateOptions();
    } catch (e) {
        listEl.innerHTML = '<div class="empty">불러오기 실패</div>';
    }
}

function toggleTemplatesExpanded() {
    templatesExpanded = !templatesExpanded;
    renderTemplateList();
}

function renderTemplateList() {
    const listEl = document.getElementById('templateList');
    if (!templatesCache.length) {
        listEl.innerHTML = '<div class="empty">등록된 상용문구가 없습니다</div>';
        return;
    }
    const shown = templatesExpanded ? templatesCache : templatesCache.slice(0, TEMPLATES_COLLAPSED_COUNT);
    const itemsHtml = shown.map(t => `
        <div class="tpl-item">
            <div>
                <div class="tpl-title">${esc(t.title)}</div>
                <div class="tpl-body">${esc(t.body)}</div>
            </div>
            <div class="tpl-actions">
                <button class="btn-ghost" onclick="editTemplate(${t.id})">수정</button>
                <button class="btn-danger" onclick="deleteTemplate(${t.id})">삭제</button>
            </div>
        </div>`).join('');
    const moreHtml = templatesCache.length > TEMPLATES_COLLAPSED_COUNT
        ? `<button class="tpl-more" onclick="toggleTemplatesExpanded()">${templatesExpanded ? '접기' : `+ 전체보기 (총 ${templatesCache.length}개)`}</button>`
        : '';
    listEl.innerHTML = itemsHtml + moreHtml;
}

function editTemplate(id) {
    const t = templatesCache.find(t => t.id === id);
    if (!t) return;
    document.getElementById('tplEditId').value = t.id;
    document.getElementById('tplTitleInput').value = t.title;
    document.getElementById('tplBodyInput').value = t.body;
}

function resetTemplateForm() {
    document.getElementById('tplEditId').value = '';
    document.getElementById('tplTitleInput').value = '';
    document.getElementById('tplBodyInput').value = '';
}

async function saveTemplate() {
    const id = document.getElementById('tplEditId').value;
    const title = document.getElementById('tplTitleInput').value.trim();
    const body = document.getElementById('tplBodyInput').value.trim();
    if (!title || !body) { showToast('제목과 내용을 입력하세요', 'bad'); return; }
    const url = id ? `/api/templates/${id}` : '/api/templates';
    const method = id ? 'PUT' : 'POST';
    const r = await fetch(url, { method, headers: {'Content-Type':'application/json'}, body: JSON.stringify({title, body}) });
    const d = await r.json();
    if (d.ok) { resetTemplateForm(); loadTemplates(); showToast('상용문구를 저장했습니다', 'ok'); }
    else showToast('저장 실패: ' + (d.error || ''), 'bad');
}

async function deleteTemplate(id) {
    const t = templatesCache.find(t => t.id === id);
    if (!await confirmDialog('상용문구 삭제', `"${t ? t.title : ''}" 문구를 삭제할까요?`, '삭제')) return;
    await fetch(`/api/templates/${id}`, { method: 'DELETE' });
    loadTemplates();
    showToast('상용문구를 삭제했습니다', 'ok');
}

// ── 업무외 자동발송 ──
function renderAutoReplyTemplateOptions() {
    const sel = document.getElementById('autoReplyTemplateSelect');
    const current = sel.value;
    sel.innerHTML = '<option value="">— 자동발송할 상용문구 선택 —</option>' +
        templatesCache.map(t => `<option value="${t.id}">${esc(t.title)}</option>`).join('');
    if (current) sel.value = current;
}

async function loadAutoReplySettings() {
    try {
        const r = await fetch('/api/settings/auto_reply');
        const d = await r.json();
        document.getElementById('autoReplyEnabled').checked = !!d.enabled;
        renderAutoReplyTemplateOptions();
        if (d.template_id) document.getElementById('autoReplyTemplateSelect').value = d.template_id;
        // 토글이 켜져 있으면 업무시간과 무관하게 바로 발송되므로(공휴일처럼
        // 요일상 평일이지만 자리를 비운 날 대응), 업무시간 여부는 참고
        // 정보로만 보여주고 "대기 상태"처럼 발송이 막힌다고 오해하게 하지
        // 않는다.
        const statusEl = document.getElementById('autoReplyStatus');
        if (!d.enabled) {
            statusEl.textContent = '자동발송이 꺼져 있습니다.';
        } else if (d.business_hours_now) {
            statusEl.textContent = '지금은 업무시간이지만 자동발송이 켜져 있어 바로 발송됩니다. 출근하면 꺼주세요.';
        } else {
            statusEl.textContent = '지금은 업무외 시간입니다. 자동발송이 켜져 있습니다.';
        }
    } catch (e) {}
}

async function saveAutoReplySettings() {
    const enabled = document.getElementById('autoReplyEnabled').checked;
    const templateId = document.getElementById('autoReplyTemplateSelect').value;
    if (enabled && !templateId) {
        showToast('자동발송할 상용문구를 먼저 선택하세요', 'bad');
        document.getElementById('autoReplyEnabled').checked = false;
        return;
    }
    try {
        await fetch('/api/settings/auto_reply', {
            method: 'PUT', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({enabled, template_id: templateId ? Number(templateId) : null})
        });
        // 저장 직후 상태 문구("지금은 업무외 시간입니다...")가 바로 갱신되게
        // 다시 불러온다 — 안 하면 다음 폴링이나 새로고침 전까지 꺼짐/켜짐
        // 이전 문구가 그대로 남아있어서 헷갈린다.
        loadAutoReplySettings();
    } catch (e) {}
}

// ── 민원 문자 목록 (스레드) ──
let lastThreads = [];
let editingRowId = null;  // 연필 아이콘으로 지금 수정 모드인 민원(수신 문자)의 id (한 번에 하나만)
let selectedThreadIds = new Set();  // 체크박스로 골라서 병합 대상이 된 스레드(민원)의 id들
let currentPageThreadIds = [];  // 전체선택 체크박스가 대상으로 삼는, 현재 페이지에 보이는 스레드 id들
const THREADS_PER_PAGE = 10;
let currentPage = 1;  // 15초 자동 갱신으로 목록이 다시 그려져도 보던 페이지를 유지한다
let searchQuery = '';  // 번호/이름/내용/처리상태/입력/접수번호 통합 검색어(소문자로 정규화해서 저장)
let periodFilter = 'month';   // 서버에서 받아올 기간 — 오늘/이번 주/이번 달/전체
let statusFilter = '';        // 처리상태 칩 필터 ('' = 전체, '__pending__' = 처리완료가 아닌 것)

// 마지막으로 화면을 본 시점 이후에 들어온 민원을 굵게 표시하기 위한 기준값.
// 브라우저에 저장해서 새로고침하거나 창을 닫았다 열어도 유지된다 — 직원이
// 자리를 비운 사이 뭐가 새로 들어왔는지 한눈에 알아보라는 용도라, 세션이
// 아니라 이 PC 기준으로 기억하는 게 맞다.
const SEEN_KEY = 'auto_sms.lastSeenComplaintId';
const storedSeen = localStorage.getItem(SEEN_KEY);
let lastSeenComplaintId = Number(storedSeen || 0);
// 이 PC에서 대시보드를 처음 여는 경우엔 기준값이 없다 — 0으로 두면 이미
// 쌓여있던 민원이 전부 NEW로 뜨면서 강조가 무의미해지므로, 첫 조회 결과의
// 가장 큰 id를 기준으로 잡아 "이 시점 이후 새로 온 것"만 표시되게 한다.
let seenBaselineNeeded = storedSeen === null;
let newComplaintIds = new Set();  // 이번에 "새로 온 것"으로 표시할 민원 id들

// 기간 칩 → /api/messages?since=YYYY-MM-DD 로 넘길 시작 날짜.
// 'all'이면 since를 아예 안 보내서 전체를 받는다.
function periodSinceDate() {
    const d = new Date();
    if (periodFilter === 'today') {
        // 그대로 오늘
    } else if (periodFilter === 'week') {
        // 월요일 시작 기준 — 일요일(0)이면 지난 월요일까지 6일 되돌린다.
        const dow = (d.getDay() + 6) % 7;
        d.setDate(d.getDate() - dow);
    } else if (periodFilter === 'month') {
        d.setDate(1);
    } else {
        return null;
    }
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function setPeriod(period) {
    periodFilter = period;
    document.querySelectorAll('[data-period]').forEach(el => {
        el.classList.toggle('active', el.dataset.period === period);
    });
    currentPage = 1;
    loadMessages();   // 기간이 바뀌면 서버에서 다시 받아와야 한다
}

function setStatusFilter(status) {
    statusFilter = status;
    document.querySelectorAll('[data-status]').forEach(el => {
        el.classList.toggle('active', el.dataset.status === status);
    });
    currentPage = 1;
    renderThreads();  // 상태 필터는 이미 받아온 목록 안에서만 거르면 된다
}

function threadMatchesStatus(t) {
    if (!statusFilter) return true;
    const s = t.complaint.status || '접수';
    if (statusFilter === '__pending__') return s !== '처리완료';
    return s === statusFilter;
}

function onSearchInput(value) {
    searchQuery = (value || '').trim().toLowerCase();
    document.getElementById('searchRow').classList.toggle('has-value', searchQuery.length > 0);
    currentPage = 1;
    renderThreads();
}

function clearSearch() {
    const input = document.getElementById('searchInput');
    input.value = '';
    onSearchInput('');
    input.focus();
}

// 민원(수신) 본문뿐 아니라 그 밑에 달린 답신 본문까지 훑는다 — 답장에만
// 있는 단어로 검색했을 때 아무것도 안 나오던 문제가 있었다.
function threadMatchesSearch(t) {
    if (!searchQuery) return true;
    const m = t.complaint;
    const fields = [m.phone_number, m.contact_name, m.body, m.status, m.manual_input, m.receipt_no];
    for (const rp of (t.replies || [])) fields.push(rp.body);
    return fields.some(v => (v || '').toLowerCase().includes(searchQuery));
}

// created_at은 서버가 "YYYY-MM-DD HH:MM:SS"(로컬시각)로 내려주므로 같은 형식으로 오늘 날짜를 만들어 앞부분만 비교한다
function todayLocalDateStr() {
    const d = new Date();
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// KPI 카드(오늘 접수/미처리/처리완료율)와 왼쪽 필터 패널의 처리상태별
// 개수를 한 번에 계산한다 — 필터링 전 lastThreads 전체를 기준으로 세어야
// "지금 접수를 눌러도 이만큼 더 있다"는 개수가 필터 결과와 상관없이
// 항상 맞기 때문에, threadMatchesStatus() 필터를 거치기 전에 호출한다.
function updateHeadStats() {
    const today = todayLocalDateStr();
    const counts = { '': 0, '__pending__': 0 };
    STATUS_OPTIONS.forEach(s => counts[s] = 0);
    let todayCount = 0;
    for (const t of lastThreads) {
        const m = t.complaint;
        if (m.direction !== 'in') continue;  // 실제 민원(수신)만 집계 — 답신만 있는 orphan 스레드는 제외
        if ((m.created_at || '').startsWith(today)) todayCount++;
        const s = m.status || '접수';
        counts['']++;
        if (s !== '처리완료') counts['__pending__']++;
        if (counts[s] !== undefined) counts[s]++;
    }
    document.getElementById('statToday').textContent = `${todayCount}`;
    document.getElementById('statPending').textContent = `${counts['__pending__']}`;
    const rate = counts[''] ? Math.round((counts['처리완료'] / counts['']) * 100) : 0;
    document.getElementById('statRate').textContent = `${rate}%`;
    document.querySelectorAll('.status-row').forEach(row => {
        const badge = row.querySelector('.count-badge');
        if (badge) badge.textContent = counts[row.dataset.status] ?? 0;
    });
}

// 마지막으로 본 민원 id보다 큰 것들을 "새로 온 민원"으로 표시해둔다.
// 표시만 갱신하고 기준값(lastSeenComplaintId)은 markAllSeen()에서만 올리므로,
// 15초 폴링이 돌아도 한 번 새 걸로 뜬 민원은 직원이 확인할 때까지 계속
// 강조된 채로 남는다.
function refreshNewComplaints() {
    let maxId = lastSeenComplaintId;
    for (const t of lastThreads) {
        const m = t.complaint;
        if (m.direction !== 'in') continue;
        if (m.id > maxId) maxId = m.id;
    }
    if (seenBaselineNeeded) {
        // 첫 조회 — 지금까지 쌓인 건 전부 "본 것"으로 두고 여기서부터 센다.
        seenBaselineNeeded = false;
        lastSeenComplaintId = maxId;
        localStorage.setItem(SEEN_KEY, String(maxId));
    }
    for (const t of lastThreads) {
        const m = t.complaint;
        if (m.direction === 'in' && m.id > lastSeenComplaintId) newComplaintIds.add(m.id);
    }
    updateNewBanner(maxId);
}

function updateNewBanner(maxId) {
    // 배너 자체는 renderBanners()가 그리므로 여기서는 개수만 넘겨둔다.
    pendingNewCount = newComplaintIds.size;
    pendingNewMaxId = maxId;
    renderBanners();
}

let pendingNewCount = 0;
let pendingNewMaxId = 0;

function markAllSeen() {
    lastSeenComplaintId = Math.max(lastSeenComplaintId, pendingNewMaxId);
    localStorage.setItem(SEEN_KEY, String(lastSeenComplaintId));
    newComplaintIds.clear();
    pendingNewCount = 0;
    renderBanners();
    renderThreads();
}

async function loadMessages() {
    // 15초마다 자동 갱신되는데, 그 사이 직원이 입력/접수번호 칸에 뭔가
    // 타이핑 중이거나 답신 상자에 내용을 쓰는 중이면 통째로 다시 그리면서
    // 입력 중인 내용이 날아가버린다 — 그 동안은 이번 갱신을 건너뛴다.
    const a = document.activeElement;
    if (a && (a.classList.contains('cell-input') || a.closest('.send-box'))) return;
    const listEl = document.getElementById('threadList');
    try {
        const since = periodSinceDate();
        const r = await fetch('/api/messages' + (since ? `?since=${since}` : ''));
        const d = await r.json();
        lastThreads = d.threads || [];
        refreshNewComplaints();
        renderThreads();
    } catch (e) {
        listEl.innerHTML = '<div class="empty">불러오기 실패</div>';
    }
}

// 연필 아이콘을 누르면 그 민원만 수정 모드(입력창)로 바뀐다 — 매번 다시
// 서버에서 받아올 필요 없이 방금 받아온 목록(lastThreads)으로 다시 그린다.
function toggleEditRow(id) {
    editingRowId = (editingRowId === id) ? null : id;
    renderThreads();
}

function toggleSendBox(idx) {
    document.getElementById(`sendBox-${idx}`).style.display = 'block';
    document.getElementById(`sendToggle-${idx}`).style.display = 'none';
}

// 같은 민원인이 시간차를 두고 다시 보내서 스레드가 갈라진 경우, 체크박스로
// 여러 스레드를 골라뒀다가 한 번에 병합한다.
function toggleThreadSelect(id, checked) {
    if (checked) selectedThreadIds.add(id); else selectedThreadIds.delete(id);
    updateMergeBar();
    syncSelectAllCheckbox();
}

// 헤더의 전체선택 체크박스 — 현재 페이지에 보이는 스레드만 대상으로 한다.
function toggleSelectAllThreads(checked) {
    currentPageThreadIds.forEach(id => {
        if (checked) selectedThreadIds.add(id); else selectedThreadIds.delete(id);
    });
    renderThreads();
}

function syncSelectAllCheckbox() {
    const box = document.getElementById('selectAllCheckbox');
    if (!box) return;
    const total = currentPageThreadIds.length;
    const selected = currentPageThreadIds.filter(id => selectedThreadIds.has(id)).length;
    box.checked = total > 0 && selected === total;
    box.indeterminate = selected > 0 && selected < total;
}

function clearThreadSelection() {
    selectedThreadIds.clear();
    renderThreads();
}

function updateMergeBar() {
    const bar = document.getElementById('mergeBar');
    const count = selectedThreadIds.size;
    if (count === 0) { bar.style.display = 'none'; return; }
    bar.style.display = 'flex';
    document.getElementById('mergeCount').textContent = `${count}개 선택됨`;
    document.getElementById('mergeBtn').disabled = count < 2;
}

async function mergeSelectedThreads() {
    const ids = Array.from(selectedThreadIds);
    if (ids.length < 2) return;
    if (!await confirmDialog('민원 병합', `선택한 ${ids.length}개 민원을 하나의 스레드로 합칠까요?`, '병합', false)) return;
    try {
        const r = await fetch('/api/threads/merge', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({complaint_ids: ids})
        });
        const d = await r.json();
        if (r.ok && d.ok) {
            selectedThreadIds.clear();
            loadMessages();
            showToast(`${ids.length}개 민원을 합쳤습니다`, 'ok');
        } else {
            showToast('병합 실패: ' + (d.error || '알 수 없는 오류'), 'bad');
        }
    } catch (e) {
        showToast('오류: ' + e.message, 'bad');
    }
}

// 화면에 보이는 그대로(민원 + 그 밑에 달린 답신들 전부)를 지운다 —
// 되돌릴 수 없는 작업이라 삭제 전에 반드시 한 번 더 확인창을 띄운다.
async function deleteSelectedThreads() {
    const ids = Array.from(selectedThreadIds);
    if (ids.length === 0) return;
    if (!await confirmDialog(
            '민원 삭제',
            `선택한 ${ids.length}개 민원을 삭제할까요?\n답신 기록도 함께 삭제되며 되돌릴 수 없습니다.`,
            '삭제')) return;
    const allIds = [];
    lastThreads.forEach(t => {
        if (selectedThreadIds.has(t.complaint.id)) {
            allIds.push(t.complaint.id);
            t.replies.forEach(r => allIds.push(r.id));
        }
    });
    try {
        const r = await fetch('/api/messages/delete', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ids: allIds})
        });
        const d = await r.json();
        if (r.ok && d.ok) {
            selectedThreadIds.clear();
            loadMessages();
            showToast(`${ids.length}개 민원을 삭제했습니다`, 'ok');
        } else {
            showToast('삭제 실패: ' + (d.error || '알 수 없는 오류'), 'bad');
        }
    } catch (e) {
        showToast('오류: ' + e.message, 'bad');
    }
}

function onReplyTemplateChange(selectEl) {
    const ta = selectEl.closest('.send-box').querySelector('textarea');
    const t = templatesCache.find(t => String(t.id) === selectEl.value);
    if (t) ta.value = t.body;
}

async function sendReply(phone, complaintId, btn) {
    const box = btn.closest('.send-box');
    const ta = box.querySelector('textarea');
    const body = ta.value.trim();
    if (!body) { showToast('보낼 내용을 입력하세요', 'bad'); return; }
    btn.disabled = true;
    try {
        const r = await fetch('/api/send', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({phone_number: phone, body, complaint_id: complaintId})
        });
        const d = await r.json();
        if (r.ok && d.ok) {
            ta.value = '';
            loadMessages();
            showToast(`${phone}로 발송했습니다`, 'ok');
        } else {
            showToast('발송 실패: ' + (d.error || '알 수 없는 오류'), 'bad');
        }
    } catch (e) {
        showToast('오류: ' + e.message, 'bad');
    } finally {
        btn.disabled = false;
    }
}

function goToPage(n) {
    currentPage = n;
    renderThreads();
}

function renderPagination(totalPages) {
    if (totalPages <= 1) return '';
    const btn = (label, page, opts = {}) => `
        <button class="page-btn ${opts.active ? 'active' : ''}" ${opts.disabled ? 'disabled' : ''} onclick="goToPage(${page})">${label}</button>`;
    let pages = '';
    for (let p = 1; p <= totalPages; p++) {
        pages += btn(p, p, { active: p === currentPage });
    }
    return `
        <div class="pagination">
            ${btn('‹ 이전', currentPage - 1, { disabled: currentPage === 1 })}
            ${pages}
            ${btn('다음 ›', currentPage + 1, { disabled: currentPage === totalPages })}
        </div>`;
}

function renderThreads() {
    const listEl = document.getElementById('threadList');
    updateHeadStats();
    if (!lastThreads.length) {
        listEl.innerHTML = '<div class="empty">이 기간에 저장된 메시지가 없습니다</div>';
        currentPageThreadIds = [];
        updateMergeBar();
        syncSelectAllCheckbox();
        return;
    }
    const filteredThreads = lastThreads.filter(t => threadMatchesSearch(t) && threadMatchesStatus(t));
    if (!filteredThreads.length) {
        listEl.innerHTML = '<div class="empty">조건에 맞는 민원이 없습니다</div>';
        currentPageThreadIds = [];
        updateMergeBar();
        syncSelectAllCheckbox();
        return;
    }
    const totalPages = Math.max(1, Math.ceil(filteredThreads.length / THREADS_PER_PAGE));
    currentPage = Math.min(Math.max(1, currentPage), totalPages);
    const pageStart = (currentPage - 1) * THREADS_PER_PAGE;
    const pageThreads = filteredThreads.slice(pageStart, pageStart + THREADS_PER_PAGE);
    currentPageThreadIds = pageThreads.map(t => t.complaint.id);
    const tplOptions = templatesCache.map(t => `<option value="${t.id}">${esc(t.title)}</option>`).join('');
    listEl.innerHTML = pageThreads.map((t, idx) => {
        const m = t.complaint;
        const isComplaint = m.direction === 'in';
        const editing = editingRowId === m.id;

        let statusHtml = '';
        let inputHtml = '';
        let receiptHtml = '';
        let editBtnHtml = '';
        if (isComplaint) {
            const statusVal = m.status || '접수';
            statusHtml = editing
                ? `<select onchange="updateMessageStatus(${m.id}, this.value)">
                       ${STATUS_OPTIONS.map(s => `<option value="${esc(s)}" ${s === statusVal ? 'selected' : ''}>${esc(s)}</option>`).join('')}
                   </select>`
                : `<span class="status-pill st-${statusVal}">${esc(statusVal)}</span>`;
            inputHtml = editing
                ? `<select class="cell-input" data-id="${m.id}" data-field="manual_input" onchange="saveMessageCell(this)">
                       ${MANUAL_INPUT_OPTIONS.map(o => `<option value="${esc(o)}" ${o === (m.manual_input || '') ? 'selected' : ''}>${o === '' ? '-' : esc(o)}</option>`).join('')}
                   </select>`
                : (m.manual_input ? `<span class="tag">${esc(m.manual_input)}</span>` : `<span class="tag tag-empty">-</span>`);
            receiptHtml = editing
                ? `<input class="cell-input" data-id="${m.id}" data-field="receipt_no" value="${esc(m.receipt_no || '')}" placeholder="접수번호" onblur="saveMessageCell(this)">`
                : (m.receipt_no ? `<span class="tag">${esc(m.receipt_no)}</span>` : `<span class="tag tag-empty">-</span>`);
            editBtnHtml = `<button class="icon-btn" onclick="toggleEditRow(${m.id})" title="${editing ? '수정 완료' : '수정'}">${editing ? ICON_CHECK : ICON_PENCIL}</button>`;
        }

        const repliesHtml = t.replies.map(rp => `
            <div class="reply">
                <div class="reply-body"><span class="pill ${rp.direction === 'in' ? 'pill-in' : 'pill-out'}">${rp.direction === 'in' ? '수신' : '발신'}</span>${rp.auto_sent ? '<span class="pill pill-muted">자동</span>' : ''}${esc(rp.body)}</div>
                <div class="reply-time">${esc(formatDateTime(rp))}</div>
            </div>`).join('');

        const checked = selectedThreadIds.has(m.id) ? 'checked' : '';
        const isNew = isComplaint && newComplaintIds.has(m.id);

        return `
            <div class="thread${isNew ? ' is-new' : ''}">
                <div class="msg-row">
                    <div class="select-col"><input type="checkbox" ${checked} onchange="toggleThreadSelect(${m.id}, this.checked)" title="병합할 스레드로 선택"></div>
                    <div class="meta">${esc(formatDateTime(m))}</div>
                    <div class="phone">${esc(m.phone_number)}</div>
                    <div class="name">${esc(m.contact_name || '-')}</div>
                    <div class="msg-body">${isNew ? '<span class="new-badge">NEW</span>' : ''}<span class="pill ${isComplaint ? 'pill-in' : 'pill-out'}">${isComplaint ? '수신' : '발신'}</span>${esc(m.body)}</div>
                    <div class="status-col">${statusHtml}</div>
                    <div class="input-col">${inputHtml}</div>
                    <div class="receipt-col">${receiptHtml}</div>
                    <div class="edit-col">${editBtnHtml}</div>
                </div>
                <div class="replies">${repliesHtml}</div>
                <button class="toggle-send" id="sendToggle-${idx}" onclick="toggleSendBox(${idx})">+ 문자발송</button>
                <div class="send-box" id="sendBox-${idx}" style="display:none;">
                    <div class="row">
                        <select onchange="onReplyTemplateChange(this)">
                            <option value="">— 상용문구 —</option>
                            ${tplOptions}
                        </select>
                        <textarea placeholder="보낼 내용"></textarea>
                        <button class="btn-primary" onclick="sendReply('${esc(m.phone_number)}', ${m.id}, this)">발송</button>
                    </div>
                </div>
            </div>`;
    }).join('') + renderPagination(totalPages);
    updateMergeBar();
    syncSelectAllCheckbox();
}

// 두 칸(입력/접수번호) 중 하나에서 포커스가 빠지면, 그 민원의 두 값을
// 한꺼번에 저장한다 — 서버가 두 컬럼을 통째로 덮어쓰는 방식이라(app.py 참고)
// 하나만 보내면 나머지 한 칸이 빈 값으로 지워지기 때문에 항상 같이 보낸다.
// 처리상태는 이 함수가 아니라 updateMessageStatus()가 따로 관리한다.
async function saveMessageCell(input) {
    const id = Number(input.dataset.id);
    const row = input.closest('.msg-row');
    const get = field => row.querySelector(`[data-field="${field}"]`).value.trim();
    const manual_input = get('manual_input');
    const receipt_no = get('receipt_no');
    try {
        const r = await fetch(`/api/messages/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ manual_input, receipt_no }),
        });
        if (r.ok) {
            const c = findComplaintById(id);
            if (c) { c.manual_input = manual_input; c.receipt_no = receipt_no; }
            input.classList.add('saved');
            setTimeout(() => input.classList.remove('saved'), 800);
        }
    } catch (e) {}
}

// ── 우측 상단 톱니바퀴 설정 메뉴 ──
function toggleSettingsMenu(e) {
    e.stopPropagation();
    const panel = document.getElementById('settingsPanel');
    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
}

// 메뉴 바깥을 클릭하면 닫히게 한다.
document.addEventListener('click', (e) => {
    const menu = document.getElementById('settingsMenu');
    if (menu && !menu.contains(e.target)) {
        document.getElementById('settingsPanel').style.display = 'none';
    }
});

async function shutdownServer() {
    if (!await confirmDialog(
            '서버 종료',
            '대시보드와 문자 감시 데몬이 모두 중지됩니다.\n종료하면 새 민원 문자가 저장되지 않습니다.',
            '종료')) return;
    try {
        await fetch('/api/shutdown', { method: 'POST' });
    } catch (e) {
        // 서버가 응답을 보내는 도중/직후 연결이 끊길 수 있어 에러는 무시한다.
    }
    // 종료 후에는 폴링이 전부 실패하면서 "감시 중단" 배너가 뜨는 게
    // 오히려 혼란스러우므로, 주기 갱신을 멈추고 안내만 남긴다.
    stopPolling();
    document.getElementById('banners').innerHTML = `
        <div class="banner banner-warn">
            <span class="banner-text">서버를 종료했습니다. 이 창은 닫으셔도 됩니다. 다시 쓰려면 start_server.bat을 실행하세요.</span>
        </div>`;
}

// ── 운영 상태 (감시 데몬 / 업무시간 중 자동발송) ──
// 이 시스템이 조용히 실패하는 경우가 두 가지 있어서 화면 위쪽에서 계속
// 확인해준다.
//  (1) watch_daemon.py가 죽으면 수신 문자가 아예 저장되지 않는데, 화면은
//      "새 민원이 없는" 평소 모습과 똑같아서 아무도 눈치채지 못한다.
//  (2) 자동발송 토글은 끌 때까지 유지되므로, 출근해서 끄는 걸 잊으면
//      업무시간에 민원 넣는 사람마다 "업무시간이 아닙니다" 문자를 받는다.
let lastStatus = null;
// 첫 조회가 끝나기 전에는 "연결 끊김"으로 단정하면 안 된다 — 페이지를 막
// 열었을 때 잠깐 빨간 배너가 번쩍이는 걸 막기 위한 구분값.
let statusLoaded = false;

async function loadStatus() {
    try {
        const r = await fetch('/api/status');
        lastStatus = await r.json();
    } catch (e) {
        // 서버 자체가 안 뜨는 상황 — 감시 상태를 알 수 없으므로 그렇게 표시한다.
        lastStatus = null;
    }
    statusLoaded = true;
    renderWatcherChip();
    renderBanners();
}

function describeAgo(seconds) {
    if (seconds == null) return '기록 없음';
    if (seconds < 60) return `${seconds}초 전`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}분 전`;
    return `${Math.floor(seconds / 3600)}시간 ${Math.floor((seconds % 3600) / 60)}분 전`;
}

function renderWatcherChip() {
    const chip = document.getElementById('watcherChip');
    const text = document.getElementById('watcherText');
    chip.classList.remove('is-ok', 'is-bad', 'is-warn');
    if (!statusLoaded) return;
    if (!lastStatus) {
        text.textContent = '서버 연결 끊김';
        chip.classList.add('is-bad');
        return;
    }
    const w = lastStatus.watcher;
    if (!w.alive) {
        text.textContent = `수신 감시 중단 (${describeAgo(w.seconds_ago)})`;
        chip.classList.add('is-bad');
    } else if (!w.polling_ok) {
        // 프로세스는 살아있는데 화면을 못 읽는 상태 — 휴대폰 연결 앱이
        // 닫혔거나 창을 못 찾는 경우가 대부분이다.
        text.textContent = '수신 감시 오류 (휴대폰 연결 앱 확인)';
        chip.classList.add('is-warn');
    } else {
        text.textContent = `수신 감시 정상 (${describeAgo(w.seconds_ago)})`;
        chip.classList.add('is-ok');
    }
}

const ICON_ALERT = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>';
const ICON_BELL = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>';

function renderBanners() {
    const el = document.getElementById('banners');
    const out = [];

    if (!statusLoaded) {
        // 아직 첫 조회 중 — 아무 배너도 띄우지 않는다.
    } else if (!lastStatus) {
        out.push(`<div class="banner banner-bad">${ICON_ALERT}
            <span class="banner-text">서버에 연결하지 못했습니다. start_server.bat이 실행 중인지 확인하세요.</span></div>`);
    } else {
        const w = lastStatus.watcher;
        if (!w.alive) {
            out.push(`<div class="banner banner-bad">${ICON_ALERT}
                <span class="banner-text">수신 감시가 멈췄습니다 (마지막 확인 ${esc(describeAgo(w.seconds_ago))}).
                지금 들어오는 민원 문자가 저장되지 않습니다 — 휴대폰과 연결 앱과 watch_daemon을 확인하세요.</span></div>`);
        } else if (!w.polling_ok) {
            out.push(`<div class="banner banner-warn">${ICON_ALERT}
                <span class="banner-text">수신 감시가 휴대폰과 연결 앱 화면을 읽지 못하고 있습니다. 앱이 켜져 있는지, 휴대폰이 연결돼 있는지 확인하세요.</span></div>`);
        }
        if (lastStatus.business_hours_now && lastStatus.auto_reply_enabled) {
            out.push(`<div class="banner banner-warn">${ICON_ALERT}
                <span class="banner-text">업무시간인데 자동응답이 켜져 있습니다 — 지금 민원을 넣는 사람마다 "업무시간이 아닙니다" 문자를 받게 됩니다.</span>
                <button onclick="turnOffAutoReply()">지금 끄기</button></div>`);
        }
    }

    if (pendingNewCount > 0) {
        out.push(`<div class="banner banner-warn" style="background:var(--accent-soft);color:var(--accent);border-color:#c9d8f7;">${ICON_BELL}
            <span class="banner-text">새로 들어온 민원 ${pendingNewCount}건</span>
            <button style="background:var(--accent);color:#fff;" onclick="markAllSeen()">확인함</button></div>`);
    }

    el.innerHTML = out.join('');
}

async function turnOffAutoReply() {
    document.getElementById('autoReplyEnabled').checked = false;
    await saveAutoReplySettings();
    await loadStatus();
    showToast('자동응답을 껐습니다', 'ok');
}

// ── 주기 갱신 ──
// 서버 종료 버튼을 누른 뒤에는 폴링이 전부 실패하면서 "연결 끊김" 배너가
// 뜨는 게 오히려 혼란스러워서, 그때만 멈출 수 있게 id를 들고 있는다.
let pollTimers = [];

function startPolling() {
    pollTimers.push(setInterval(loadMessages, 15000));   // 워처가 새로 저장한 수신 문자를 화면에 자동 반영
    pollTimers.push(setInterval(loadStatus, 10000));     // 감시 중단/자동발송 경고는 좀 더 자주 확인
    pollTimers.push(setInterval(loadAutoReplySettings, 60000));  // 업무시간이 바뀌면 안내 문구도 따라가게
}

function stopPolling() {
    pollTimers.forEach(clearInterval);
    pollTimers = [];
}

loadTemplates();
loadMessages();
loadAutoReplySettings();
loadStatus();
startPolling();
