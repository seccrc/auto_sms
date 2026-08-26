function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

let templatesCache = [];
const STATUS_OPTIONS = ['', '처리중', '처리완료'];
const STATUS_LABELS = { '': '미처리', '처리중': '처리중', '처리완료': '처리완료' };

async function updateMessageStatus(id, status) {
    try {
        await fetch(`/api/messages/${id}/status`, {
            method: 'PATCH', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({status})
        });
    } catch (e) {}
}

// ── 최근 대화 상대 (수신자 드롭다운) ──
async function loadContacts() {
    const sel = document.getElementById('sendPhoneSelect');
    try {
        const r = await fetch('/api/contacts');
        const d = await r.json();
        sel.innerHTML = '<option value="">— 최근 대화 상대에서 선택 —</option>' +
            (d.contacts || []).map(c =>
                `<option value="${esc(c.phone_number)}">${esc(c.contact_name || c.phone_number)} (${esc(c.phone_number)})</option>`
            ).join('');
    } catch (e) {}
}

function onRecipientChange() {
    const sel = document.getElementById('sendPhoneSelect');
    if (sel.value) document.getElementById('sendPhoneInput').value = sel.value;
}

// ── 상용문구 ──
async function loadTemplates() {
    const listEl = document.getElementById('templateList');
    const sel = document.getElementById('sendTemplateSelect');
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
        sel.innerHTML = '<option value="">— 문구 선택 (또는 아래 직접 입력) —</option>' +
            templatesCache.map(t => `<option value="${t.id}">${esc(t.title)}</option>`).join('');
    } catch (e) {
        listEl.innerHTML = '<div class="empty">불러오기 실패</div>';
    }
}

function onTemplateChange() {
    const sel = document.getElementById('sendTemplateSelect');
    const t = templatesCache.find(t => String(t.id) === sel.value);
    if (t) document.getElementById('sendBodyInput').value = t.body;
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

// ── 발송 ──
async function sendSms() {
    const phone = (document.getElementById('sendPhoneInput').value ||
                   document.getElementById('sendPhoneSelect').value).trim();
    const body = document.getElementById('sendBodyInput').value.trim();
    const statusEl = document.getElementById('sendStatus');
    const btn = document.getElementById('sendBtn');
    if (!phone) { statusEl.textContent = '수신 번호를 선택하거나 입력하세요'; statusEl.className = 'err'; return; }
    if (!body) { statusEl.textContent = '보낼 내용을 입력하세요'; statusEl.className = 'err'; return; }

    btn.disabled = true;
    statusEl.textContent = '발송 중…';
    statusEl.className = '';
    try {
        const r = await fetch('/api/send', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({phone_number: phone, body})
        });
        const d = await r.json();
        if (r.ok && d.ok) {
            statusEl.textContent = '발송 완료';
            statusEl.className = 'ok';
            loadMessages();
            loadContacts();
        } else {
            statusEl.textContent = '실패: ' + (d.error || '알 수 없는 오류');
            statusEl.className = 'err';
        }
    } catch (e) {
        statusEl.textContent = '오류: ' + e.message;
        statusEl.className = 'err';
    } finally {
        btn.disabled = false;
    }
}

// ── 최근 메시지 ──
let lastMessages = [];
let editingRowId = null;  // 연필 아이콘으로 지금 수정 모드인 행의 메시지 id (한 번에 하나만)

async function loadMessages() {
    // 15초마다 자동 갱신되는데, 그 사이 직원이 입력/접수번호 칸에 뭔가
    // 타이핑 중이면 통째로 다시 그리면서 입력 중인 내용이 날아가버린다 —
    // 그 칸에 포커스가 있는 동안은 이번 갱신을 건너뛴다.
    if (document.activeElement && document.activeElement.classList.contains('cell-input')) return;
    const body = document.getElementById('msgTableBody');
    try {
        const r = await fetch('/api/messages?limit=100');
        const d = await r.json();
        lastMessages = d.messages || [];
        renderMessages();
    } catch (e) {
        body.innerHTML = '<tr><td colspan="10" class="empty">불러오기 실패</td></tr>';
    }
}

// 연필 아이콘을 누르면 그 행만 수정 모드(입력창)로 바뀐다 — 매번 다시
// 서버에서 받아올 필요 없이 방금 받아온 목록(lastMessages)으로 다시 그린다.
function toggleEditRow(id) {
    editingRowId = (editingRowId === id) ? null : id;
    renderMessages();
}

function renderMessages() {
    const body = document.getElementById('msgTableBody');
    if (!lastMessages.length) {
        body.innerHTML = '<tr><td colspan="10" class="empty">아직 메시지가 없습니다</td></tr>';
        return;
    }
    body.innerHTML = lastMessages.map(m => {
        const editing = editingRowId === m.id;
        const statusCell = editing
            ? `<select onchange="updateMessageStatus(${m.id}, this.value)">
                   ${STATUS_OPTIONS.map(s => `<option value="${esc(s)}" ${s === (m.status || '') ? 'selected' : ''}>${esc(STATUS_LABELS[s])}</option>`).join('')}
               </select>`
            : `<span class="pill ${m.status === '처리완료' ? 'pill-out' : (m.status === '처리중' ? 'pill-in' : 'pill-muted')}">${esc(STATUS_LABELS[m.status || ''])}</span>`;
        const inputCell = editing
            ? `<input class="cell-input" data-id="${m.id}" data-field="manual_input" value="${esc(m.manual_input || '')}" onblur="saveMessageCell(this)">`
            : esc(m.manual_input || '-');
        const receiptCell = editing
            ? `<input class="cell-input" data-id="${m.id}" data-field="receipt_no" value="${esc(m.receipt_no || '')}" onblur="saveMessageCell(this)">`
            : esc(m.receipt_no || '-');
        const repliedCell = m.replied === null
            ? '-'
            : `<span class="pill ${m.replied ? 'pill-out' : 'pill-bad'}">${m.replied ? '답신함' : '답신안함'}</span>`;
        return `
            <tr>
                <td><span class="pill ${m.direction === 'in' ? 'pill-in' : 'pill-out'}">${m.direction === 'in' ? '수신' : '발신'}</span></td>
                <td>${esc(m.phone_number)}</td>
                <td>${esc(m.contact_name || '')}</td>
                <td class="msg-body">${esc(m.body)}</td>
                <td>${esc(m.msg_time || m.created_at || '')}</td>
                <td>${statusCell}</td>
                <td>${inputCell}</td>
                <td>${receiptCell}</td>
                <td>${repliedCell}</td>
                <td><button class="icon-btn" onclick="toggleEditRow(${m.id})" title="${editing ? '수정 완료' : '수정'}">${editing ? '✓' : '✏️'}</button></td>
            </tr>`;
    }).join('');
}

// 두 칸(입력/접수번호) 중 하나에서 포커스가 빠지면, 그 행의 두 값을
// 한꺼번에 저장한다 — 서버가 두 컬럼을 통째로 덮어쓰는 방식이라(app.py 참고)
// 하나만 보내면 나머지 한 칸이 빈 값으로 지워지기 때문에 항상 같이 보낸다.
// 처리상태는 이 함수가 아니라 updateMessageStatus()가 따로 관리한다.
async function saveMessageCell(input) {
    const id = input.dataset.id;
    const row = input.closest('tr');
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

loadContacts();
loadTemplates();
loadMessages();
setInterval(loadMessages, 15000);   // 워처가 새로 저장한 수신 문자를 화면에 자동 반영
setInterval(loadContacts, 30000);
