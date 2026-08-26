function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

let templatesCache = [];
const STATUS_OPTIONS = ['접수', '부서전달', '담당자확인', '처리완료'];
const MANUAL_INPUT_OPTIONS = ['', '행정종합관찰제', '종합민원이력시스템'];

async function updateMessageStatus(id, status) {
    try {
        await fetch(`/api/messages/${id}/status`, {
            method: 'PATCH', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({status})
        });
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
    if (!title || !body) { alert('제목과 내용을 입력하세요'); return; }
    const url = id ? `/api/templates/${id}` : '/api/templates';
    const method = id ? 'PUT' : 'POST';
    const r = await fetch(url, { method, headers: {'Content-Type':'application/json'}, body: JSON.stringify({title, body}) });
    const d = await r.json();
    if (d.ok) { resetTemplateForm(); loadTemplates(); }
    else alert('저장 실패: ' + (d.error || ''));
}

async function deleteTemplate(id) {
    if (!confirm('이 상용문구를 삭제할까요?')) return;
    await fetch(`/api/templates/${id}`, { method: 'DELETE' });
    loadTemplates();
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
        const statusEl = document.getElementById('autoReplyStatus');
        statusEl.textContent = d.business_hours_now ? '지금은 업무시간이라 자동발송은 대기 상태입니다.' : '지금은 업무외 시간입니다.';
    } catch (e) {}
}

async function saveAutoReplySettings() {
    const enabled = document.getElementById('autoReplyEnabled').checked;
    const templateId = document.getElementById('autoReplyTemplateSelect').value;
    if (enabled && !templateId) {
        alert('자동발송할 상용문구를 먼저 선택하세요');
        document.getElementById('autoReplyEnabled').checked = false;
        return;
    }
    try {
        await fetch('/api/settings/auto_reply', {
            method: 'PUT', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({enabled, template_id: templateId ? Number(templateId) : null})
        });
    } catch (e) {}
}

// ── 민원 문자 목록 (스레드) ──
let lastThreads = [];
let editingRowId = null;  // 연필 아이콘으로 지금 수정 모드인 민원(수신 문자)의 id (한 번에 하나만)
let selectedThreadIds = new Set();  // 체크박스로 골라서 병합 대상이 된 스레드(민원)의 id들
const THREADS_PER_PAGE = 10;
let currentPage = 1;  // 15초 자동 갱신으로 목록이 다시 그려져도 보던 페이지를 유지한다

// created_at은 서버가 "YYYY-MM-DD HH:MM:SS"(로컬시각)로 내려주므로 같은 형식으로 오늘 날짜를 만들어 앞부분만 비교한다
function todayLocalDateStr() {
    const d = new Date();
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function updateHeadStats() {
    const today = todayLocalDateStr();
    let todayCount = 0;
    let pendingCount = 0;
    for (const t of lastThreads) {
        const m = t.complaint;
        if (m.direction !== 'in') continue;  // 실제 민원(수신)만 집계 — 답신만 있는 orphan 스레드는 제외
        if ((m.created_at || '').startsWith(today)) todayCount++;
        if ((m.status || '접수') !== '처리완료') pendingCount++;
    }
    document.getElementById('statToday').textContent = `오늘 접수 ${todayCount}건`;
    document.getElementById('statPending').textContent = `미처리 ${pendingCount}건`;
}

async function loadMessages() {
    // 15초마다 자동 갱신되는데, 그 사이 직원이 입력/접수번호 칸에 뭔가
    // 타이핑 중이거나 답신 상자에 내용을 쓰는 중이면 통째로 다시 그리면서
    // 입력 중인 내용이 날아가버린다 — 그 동안은 이번 갱신을 건너뛴다.
    const a = document.activeElement;
    if (a && (a.classList.contains('cell-input') || a.closest('.send-box'))) return;
    const listEl = document.getElementById('threadList');
    try {
        const r = await fetch('/api/messages?limit=100');
        const d = await r.json();
        lastThreads = d.threads || [];
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
    if (!confirm(`선택한 ${ids.length}개 민원을 하나의 스레드로 합칠까요?`)) return;
    try {
        const r = await fetch('/api/threads/merge', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({complaint_ids: ids})
        });
        const d = await r.json();
        if (r.ok && d.ok) {
            selectedThreadIds.clear();
            loadMessages();
        } else {
            alert('병합 실패: ' + (d.error || '알 수 없는 오류'));
        }
    } catch (e) {
        alert('오류: ' + e.message);
    }
}

function onReplyTemplateChange(selectEl) {
    const ta = selectEl.closest('.send-box').querySelector('textarea');
    const t = templatesCache.find(t => String(t.id) === selectEl.value);
    if (t) ta.value = t.body;
}

async function sendReply(phone, btn) {
    const box = btn.closest('.send-box');
    const ta = box.querySelector('textarea');
    const body = ta.value.trim();
    if (!body) { alert('보낼 내용을 입력하세요'); return; }
    btn.disabled = true;
    try {
        const r = await fetch('/api/send', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({phone_number: phone, body})
        });
        const d = await r.json();
        if (r.ok && d.ok) {
            ta.value = '';
            loadMessages();
        } else {
            alert('발송 실패: ' + (d.error || '알 수 없는 오류'));
        }
    } catch (e) {
        alert('오류: ' + e.message);
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
        listEl.innerHTML = '<div class="empty">아직 메시지가 없습니다</div>';
        updateMergeBar();
        return;
    }
    const totalPages = Math.max(1, Math.ceil(lastThreads.length / THREADS_PER_PAGE));
    currentPage = Math.min(Math.max(1, currentPage), totalPages);
    const pageStart = (currentPage - 1) * THREADS_PER_PAGE;
    const pageThreads = lastThreads.slice(pageStart, pageStart + THREADS_PER_PAGE);
    const tplOptions = templatesCache.map(t => `<option value="${t.id}">${esc(t.title)}</option>`).join('');
    listEl.innerHTML = pageThreads.map((t, idx) => {
        const m = t.complaint;
        const isComplaint = m.direction === 'in';
        const editing = editingRowId === m.id;

        let controlsHtml = '';
        let editBtnHtml = '';
        if (isComplaint) {
            const statusVal = m.status || '접수';
            const statusCell = editing
                ? `<select onchange="updateMessageStatus(${m.id}, this.value)">
                       ${STATUS_OPTIONS.map(s => `<option value="${esc(s)}" ${s === statusVal ? 'selected' : ''}>${esc(s)}</option>`).join('')}
                   </select>`
                : `<span class="status-pill st-${statusVal}">${esc(statusVal)}</span>`;
            const fieldsHtml = editing
                ? `<select class="cell-input" data-id="${m.id}" data-field="manual_input" onchange="saveMessageCell(this)">
                       ${MANUAL_INPUT_OPTIONS.map(o => `<option value="${esc(o)}" ${o === (m.manual_input || '') ? 'selected' : ''}>${o === '' ? '-' : esc(o)}</option>`).join('')}
                   </select>
                   <input class="cell-input" data-id="${m.id}" data-field="receipt_no" value="${esc(m.receipt_no || '')}" placeholder="접수번호" onblur="saveMessageCell(this)">`
                : `<span>입력: ${esc(m.manual_input || '-')}</span><span>접수번호: ${esc(m.receipt_no || '-')}</span>`;
            controlsHtml = `<div class="controls">${statusCell}<div class="fields">${fieldsHtml}</div></div>`;
            editBtnHtml = `<button class="icon-btn" onclick="toggleEditRow(${m.id})" title="${editing ? '수정 완료' : '수정'}">${editing ? '✓' : '✏️'}</button>`;
        }

        const repliesHtml = t.replies.map(rp => `
            <div class="reply">
                <div class="reply-body"><span class="pill ${rp.direction === 'in' ? 'pill-in' : 'pill-out'}">${rp.direction === 'in' ? '수신' : '발신'}</span>${rp.auto_sent ? '<span class="pill pill-muted">자동</span>' : ''}${esc(rp.body)}</div>
                <div class="reply-time">${esc(rp.msg_time || rp.created_at || '')}</div>
            </div>`).join('');

        const checked = selectedThreadIds.has(m.id) ? 'checked' : '';

        return `
            <div class="thread">
                <div class="msg-row">
                    <div class="select-col"><input type="checkbox" ${checked} onchange="toggleThreadSelect(${m.id}, this.checked)" title="병합할 스레드로 선택"></div>
                    <div class="meta">${esc(m.msg_time || m.created_at || '')}</div>
                    <div class="phone">${esc(m.phone_number)}</div>
                    <div class="name">${esc(m.contact_name || '-')}</div>
                    <div class="msg-body"><span class="pill ${isComplaint ? 'pill-in' : 'pill-out'}">${isComplaint ? '수신' : '발신'}</span>${esc(m.body)}</div>
                    <div>${controlsHtml}</div>
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
                        <button class="btn-primary" onclick="sendReply('${esc(m.phone_number)}', this)">발송</button>
                    </div>
                </div>
            </div>`;
    }).join('') + renderPagination(totalPages);
    updateMergeBar();
}

// 두 칸(입력/접수번호) 중 하나에서 포커스가 빠지면, 그 민원의 두 값을
// 한꺼번에 저장한다 — 서버가 두 컬럼을 통째로 덮어쓰는 방식이라(app.py 참고)
// 하나만 보내면 나머지 한 칸이 빈 값으로 지워지기 때문에 항상 같이 보낸다.
// 처리상태는 이 함수가 아니라 updateMessageStatus()가 따로 관리한다.
async function saveMessageCell(input) {
    const id = input.dataset.id;
    const row = input.closest('.msg-row');
    const get = field => row.querySelector(`[data-field="${field}"]`).value.trim();
    try {
        const r = await fetch(`/api/messages/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                manual_input: get('manual_input'),
                receipt_no: get('receipt_no'),
            }),
        });
        if (r.ok) {
            input.classList.add('saved');
            setTimeout(() => input.classList.remove('saved'), 800);
        }
    } catch (e) {}
}

loadTemplates();
loadMessages();
loadAutoReplySettings();
setInterval(loadMessages, 15000);   // 워처가 새로 저장한 수신 문자를 화면에 자동 반영
