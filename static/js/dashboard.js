function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

let templatesCache = [];

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
async function loadMessages() {
    const body = document.getElementById('msgTableBody');
    try {
        const r = await fetch('/api/messages?limit=100');
        const d = await r.json();
        const msgs = d.messages || [];
        if (!msgs.length) {
            body.innerHTML = '<tr><td colspan="5" class="empty">아직 메시지가 없습니다</td></tr>';
            return;
        }
        body.innerHTML = msgs.map(m => `
            <tr>
                <td><span class="pill ${m.direction === 'in' ? 'pill-in' : 'pill-out'}">${m.direction === 'in' ? '수신' : '발신'}</span></td>
                <td>${esc(m.phone_number)}</td>
                <td>${esc(m.contact_name || '')}</td>
                <td class="msg-body">${esc(m.body)}</td>
                <td>${esc(m.msg_time || m.created_at || '')}</td>
            </tr>`).join('');
    } catch (e) {
        body.innerHTML = '<tr><td colspan="5" class="empty">불러오기 실패</td></tr>';
    }
}

loadContacts();
loadTemplates();
loadMessages();
setInterval(loadMessages, 15000);   // 워처가 새로 저장한 수신 문자를 화면에 자동 반영
setInterval(loadContacts, 30000);
