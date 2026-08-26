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
async function loadTemplates() {
    const listEl = document.getElementById('templateList');
    try {
        const r = await fetch('/api/templates');
        const d = await r.json();
        templatesCache = d.templates || [];
        if (!templatesCache.length) {
            listEl.innerHTML = '<div class="empty">등록된 상용문구가 없습니다</div>';
        } else {
            listEl.innerHTML = templatesCache.map(t => `
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
        }
        renderThreads(); // 상용문구 목록이 새로 로드되면 답신 상자의 문구 드롭다운도 갱신
    } catch (e) {
        listEl.innerHTML = '<div class="empty">불러오기 실패</div>';
    }
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

// ── 민원 문자 목록 (스레드) ──
let lastThreads = [];
let editingRowId = null;  // 연필 아이콘으로 지금 수정 모드인 민원(수신 문자)의 id (한 번에 하나만)

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

function renderThreads() {
    const listEl = document.getElementById('threadList');
    if (!lastThreads.length) {
        listEl.innerHTML = '<div class="empty">아직 메시지가 없습니다</div>';
        return;
    }
    const tplOptions = templatesCache.map(t => `<option value="${t.id}">${esc(t.title)}</option>`).join('');
    listEl.innerHTML = lastThreads.map((t, idx) => {
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
                <div class="reply-body">${esc(rp.body)}</div>
                <div class="reply-time">${esc(rp.msg_time || rp.created_at || '')}</div>
            </div>`).join('');

        return `
            <div class="thread">
                <div class="msg-row">
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
    }).join('');
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
setInterval(loadMessages, 15000);   // 워처가 새로 저장한 수신 문자를 화면에 자동 반영
