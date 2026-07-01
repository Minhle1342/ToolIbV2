/**
 * Real-time Collaboration using Socket.IO
 * Captures mouse movements and active image updates to share with other users in the same project.
 */

(function () {
    // 1. Setup User Profile (Name & Color)
    const colors = [
        '#ef4444', '#f97316', '#f59e0b', '#10b981', '#06b6d4',
        '#3b82f6', '#6366f1', '#8b5cf6', '#d946ef', '#ec4899'
    ];

    let myColor = localStorage.getItem('collab_color');
    if (!myColor) {
        myColor = colors[Math.floor(Math.random() * colors.length)];
        localStorage.setItem('collab_color', myColor);
    }

    let myName = localStorage.getItem('collab_username');
    if (!myName) {
        myName = 'User_' + Math.floor(1000 + Math.random() * 9000);
        localStorage.setItem('collab_username', myName);
    }

    let myImageId = null;
    let remoteUsers = {}; // sid -> {user_name, color, image_id, x, y}
    let socket = null;
    let lastMoveTime = 0;
    let lastSentState = { x: 0, y: 0, image_id: null };

    // Direct Message State and Helpers
    let activeChatSid = null;
    let activeChatUserName = null;

    // Voice Call State and WebRTC Helpers
    let localStream = null;
    let peerConnection = null;
    let voiceCallTargetSid = null;
    let voiceCallState = 'idle'; // 'idle', 'calling', 'ringing', 'connected'
    let callTimerInterval = null;
    let callStartTime = null;

    let incomingRingInterval = null;
    let incomingRingContext = null;
    let outgoingRingInterval = null;
    let outgoingRingContext = null;

    const rtcConfig = {
        iceServers: [
            { urls: 'stun:stun.l.google.com:19302' },
            { urls: 'stun:stun1.l.google.com:19302' },
            { urls: 'stun:stun2.l.google.com:19302' }
        ]
    };

    function startIncomingRingtone() {
        stopIncomingRingtone();
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        incomingRingContext = new AudioContext();

        function playRingCycle() {
            if (!incomingRingContext || incomingRingContext.state === 'closed') return;
            const now = incomingRingContext.currentTime;
            const osc1 = incomingRingContext.createOscillator();
            const osc2 = incomingRingContext.createOscillator();
            const gain = incomingRingContext.createGain();

            osc1.frequency.setValueAtTime(440, now);
            osc2.frequency.setValueAtTime(554.37, now);

            gain.gain.setValueAtTime(0, now);
            gain.gain.linearRampToValueAtTime(0.1, now + 0.1);
            gain.gain.linearRampToValueAtTime(0.1, now + 0.8);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + 1.2);

            osc1.connect(gain);
            osc2.connect(gain);
            gain.connect(incomingRingContext.destination);

            osc1.start(now);
            osc2.start(now);
            osc1.stop(now + 1.5);
            osc2.stop(now + 1.5);
        }

        playRingCycle();
        incomingRingInterval = setInterval(playRingCycle, 2000);
    }

    function stopIncomingRingtone() {
        if (incomingRingInterval) {
            clearInterval(incomingRingInterval);
            incomingRingInterval = null;
        }
        if (incomingRingContext) {
            incomingRingContext.close().catch(() => { });
            incomingRingContext = null;
        }
    }

    function startOutgoingRingtone() {
        stopOutgoingRingtone();
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        outgoingRingContext = new AudioContext();

        function playRingback() {
            if (!outgoingRingContext || outgoingRingContext.state === 'closed') return;
            const now = outgoingRingContext.currentTime;
            const osc1 = outgoingRingContext.createOscillator();
            const osc2 = outgoingRingContext.createOscillator();
            const gain = outgoingRingContext.createGain();

            osc1.frequency.setValueAtTime(440, now);
            osc2.frequency.setValueAtTime(480, now);

            gain.gain.setValueAtTime(0, now);
            gain.gain.linearRampToValueAtTime(0.05, now + 0.1);
            gain.gain.linearRampToValueAtTime(0.05, now + 1.2);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + 1.5);

            osc1.connect(gain);
            osc2.connect(gain);
            gain.connect(outgoingRingContext.destination);

            osc1.start(now);
            osc2.start(now);
            osc1.stop(now + 1.6);
            osc2.stop(now + 1.6);
        }

        playRingback();
        outgoingRingInterval = setInterval(playRingback, 3000);
    }

    function stopOutgoingRingtone() {
        if (outgoingRingInterval) {
            clearInterval(outgoingRingInterval);
            outgoingRingInterval = null;
        }
        if (outgoingRingContext) {
            outgoingRingContext.close().catch(() => { });
            outgoingRingContext = null;
        }
    }

    function updateCallTimer() {
        const timerEl = document.getElementById('collabActiveCallTimer');
        if (!timerEl || !callStartTime) return;
        const diff = Math.floor((Date.now() - callStartTime) / 1000);
        const mins = String(Math.floor(diff / 60)).padStart(2, '0');
        const secs = String(diff % 60).padStart(2, '0');
        timerEl.textContent = `${mins}:${secs}`;
    }

    function startCallTimer() {
        callStartTime = Date.now();
        updateCallTimer();
        if (callTimerInterval) clearInterval(callTimerInterval);
        callTimerInterval = setInterval(updateCallTimer, 1000);
    }

    function stopCallTimer() {
        if (callTimerInterval) {
            clearInterval(callTimerInterval);
            callTimerInterval = null;
        }
        callStartTime = null;
    }

    function playNotificationSound() {
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;
            const ctx = new AudioContext();
            const now = ctx.currentTime;
            const duration = 2.0;

            const mainGain = ctx.createGain();
            mainGain.gain.setValueAtTime(0.12, now);
            // Decay over 2 seconds
            mainGain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
            mainGain.connect(ctx.destination);

            // A warm chime using sine waves: C5, E5, G5, C6
            const notes = [
                { freq: 523.25, delay: 0.0 },
                { freq: 659.25, delay: 0.1 },
                { freq: 783.99, delay: 0.2 },
                { freq: 1046.50, delay: 0.3 }
            ];

            notes.forEach(note => {
                const osc = ctx.createOscillator();
                const gainNode = ctx.createGain();

                osc.type = 'sine';
                osc.frequency.setValueAtTime(note.freq, now + note.delay);

                // Note envelope
                gainNode.gain.setValueAtTime(0, now);
                gainNode.gain.linearRampToValueAtTime(0.3, now + note.delay + 0.03);
                gainNode.gain.exponentialRampToValueAtTime(0.0001, now + note.delay + 1.2);

                osc.connect(gainNode);
                gainNode.connect(mainGain);

                osc.start(now + note.delay);
                osc.stop(now + duration);
            });

            // Auto-close context after exactly 2 seconds + some buffer
            setTimeout(() => {
                ctx.close().catch(() => { });
            }, 2100);
        } catch (e) {
            console.warn('[Collab] Audio notification error:', e);
        }
    }

    let remoteCandidateQueue = [];
    let remoteAudioElement = null;

    function playRemoteStream(stream) {
        if (!remoteAudioElement) {
            remoteAudioElement = document.createElement('audio');
            remoteAudioElement.id = 'collabRemoteAudio';
            remoteAudioElement.autoplay = true;
            document.body.appendChild(remoteAudioElement);
        }
        remoteAudioElement.srcObject = stream;
    }

    function cleanupWebRTC() {
        stopCallTimer();
        stopIncomingRingtone();
        stopOutgoingRingtone();

        if (localStream) {
            localStream.getTracks().forEach(track => track.stop());
            localStream = null;
        }
        if (peerConnection) {
            peerConnection.close();
            peerConnection = null;
        }
        if (remoteAudioElement) {
            remoteAudioElement.srcObject = null;
            remoteAudioElement.remove();
            remoteAudioElement = null;
        }
        remoteCandidateQueue = [];
        voiceCallTargetSid = null;
        voiceCallState = 'idle';
    }

    async function startWebRTCCall(targetSid) {
        try {
            localStream = await navigator.mediaDevices.getUserMedia({ audio: true });

            peerConnection = new RTCPeerConnection(rtcConfig);

            localStream.getTracks().forEach(track => {
                peerConnection.addTrack(track, localStream);
            });

            peerConnection.ontrack = (event) => {
                console.log('[Collab] Received remote track');
                playRemoteStream(event.streams[0]);
            };

            peerConnection.onicecandidate = (event) => {
                if (event.candidate && socket && socket.connected) {
                    socket.emit('collab_wertc_signal', {
                        target_sid: targetSid,
                        signal: { type: 'candidate', candidate: event.candidate }
                    });
                }
            };

            const offer = await peerConnection.createOffer();
            await peerConnection.setLocalDescription(offer);

            socket.emit('collab_wertc_signal', {
                target_sid: targetSid,
                signal: { type: 'offer', sdp: offer.sdp }
            });

        } catch (err) {
            console.error('[Collab] WebRTC start call error:', err);
            showToastError("Không thể truy cập microphone.");
            cleanupWebRTC();
            hideCallUI();
        }
    }

    async function acceptWebRTCCall(targetSid) {
        try {
            stopIncomingRingtone();

            localStream = await navigator.mediaDevices.getUserMedia({ audio: true });

            peerConnection = new RTCPeerConnection(rtcConfig);

            localStream.getTracks().forEach(track => {
                peerConnection.addTrack(track, localStream);
            });

            peerConnection.ontrack = (event) => {
                console.log('[Collab] Received remote track');
                playRemoteStream(event.streams[0]);
            };

            peerConnection.onicecandidate = (event) => {
                if (event.candidate && socket && socket.connected) {
                    socket.emit('collab_wertc_signal', {
                        target_sid: targetSid,
                        signal: { type: 'candidate', candidate: event.candidate }
                    });
                }
            };

            socket.emit('collab_accept_call', { target_sid: targetSid });

            showCallUI('connected', remoteUsers[targetSid]?.user_name || 'User', targetSid);

        } catch (err) {
            console.error('[Collab] WebRTC accept call error:', err);
            showToastError("Không thể truy cập microphone.");
            if (socket && socket.connected) {
                socket.emit('collab_reject_call', { target_sid: targetSid });
            }
            cleanupWebRTC();
            hideCallUI();
        }
    }

    function showToastInfo(message) {
        const notifContainer = document.getElementById('collabNotificationContainer');
        if (!notifContainer) return;

        const toast = document.createElement('div');
        toast.className = 'collab-toast-enter pointer-events-auto bg-slate-900 border border-slate-700/50 rounded-xl shadow-xl p-3 flex gap-2.5 items-center backdrop-blur-md w-72';
        toast.innerHTML = `
            <div class="flex-shrink-0 w-6 h-6 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center">
                <i class="fa-solid fa-circle-info text-xs"></i>
            </div>
            <div class="flex-1 text-[11px] text-left text-slate-300 font-semibold">
                ${message}
            </div>
        `;
        notifContainer.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-10px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    function showToastError(message) {
        const notifContainer = document.getElementById('collabNotificationContainer');
        if (!notifContainer) return;

        const toast = document.createElement('div');
        toast.className = 'collab-toast-enter pointer-events-auto bg-slate-900 border border-red-500/30 rounded-xl shadow-xl p-3 flex gap-2.5 items-center backdrop-blur-md w-72';
        toast.innerHTML = `
            <div class="flex-shrink-0 w-6 h-6 rounded-full bg-red-500/20 text-red-400 flex items-center justify-center">
                <i class="fa-solid fa-circle-exclamation text-xs"></i>
            </div>
            <div class="flex-1 text-[11px] text-left text-slate-300 font-semibold">
                ${message}
            </div>
        `;
        notifContainer.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-10px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    function ensureCallUI() {
        if (document.getElementById('collabCallWidget')) return;

        const widget = document.createElement('div');
        widget.id = 'collabCallWidget';
        widget.className = 'fixed bottom-6 right-6 z-[9999] hidden transition-all duration-300 transform scale-95 opacity-0';

        widget.innerHTML = `
            <div class="bg-slate-900/95 backdrop-blur-md border border-slate-700/50 rounded-2xl shadow-2xl p-5 w-80 text-white flex flex-col items-center space-y-4">
                <div class="w-full flex items-center justify-between">
                    <span class="text-[10px] font-bold tracking-wider uppercase text-blue-400">Cuộc gọi thoại</span>
                    <div id="collabCallStatusIndicator" class="flex items-center gap-1.5">
                        <span id="collabCallStatusDot" class="w-2.5 h-2.5 rounded-full bg-blue-500 animate-pulse"></span>
                        <span id="collabCallStatusText" class="text-[11px] font-medium text-slate-300">Đang gọi...</span>
                    </div>
                </div>

                <div class="flex flex-col items-center space-y-2">
                    <div id="collabCallAvatar" class="w-16 h-16 rounded-full flex items-center justify-center text-xl font-bold shadow-lg border border-slate-700 select-none transition-all text-white">
                        U
                    </div>
                    <div id="collabCallName" class="text-sm font-bold text-white">UserName</div>
                    <div id="collabActiveCallTimer" class="text-xs text-slate-400 font-mono">00:00</div>
                </div>

                <div class="w-full pt-2 flex items-center justify-center gap-3">
                    <button id="collabCallMuteBtn" class="w-11 h-11 rounded-full bg-slate-800 hover:bg-slate-700 active:scale-95 text-slate-300 flex items-center justify-center transition-all border border-slate-700/50 hidden" title="Mute/Unmute Mic">
                        <i class="fa-solid fa-microphone text-sm"></i>
                    </button>
                    <button id="collabCallAcceptBtn" class="w-12 h-12 rounded-full bg-emerald-600 hover:bg-emerald-500 active:scale-95 text-white flex items-center justify-center transition-all shadow-lg shadow-emerald-500/20 hidden" title="Nhận cuộc gọi">
                        <i class="fa-solid fa-phone text-lg text-white"></i>
                    </button>
                    <button id="collabCallRejectBtn" class="w-12 h-12 rounded-full bg-red-600 hover:bg-red-500 active:scale-95 text-white flex items-center justify-center transition-all shadow-lg shadow-red-500/20 hidden" title="Từ chối">
                        <i class="fa-solid fa-phone-slash text-lg text-white"></i>
                    </button>
                    <button id="collabCallHangupBtn" class="w-12 h-12 rounded-full bg-red-600 hover:bg-red-500 active:scale-95 text-white flex items-center justify-center transition-all shadow-lg shadow-red-500/20" title="Gác máy / Hủy gọi">
                        <i class="fa-solid fa-phone-slash text-lg text-white"></i>
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(widget);

        document.getElementById('collabCallAcceptBtn').onclick = () => {
            if (voiceCallTargetSid) {
                acceptWebRTCCall(voiceCallTargetSid);
            }
        };

        document.getElementById('collabCallRejectBtn').onclick = () => {
            if (voiceCallTargetSid) {
                socket.emit('collab_reject_call', { target_sid: voiceCallTargetSid });
                cleanupWebRTC();
                hideCallUI();
            }
        };

        document.getElementById('collabCallHangupBtn').onclick = () => {
            if (voiceCallTargetSid) {
                if (voiceCallState === 'calling') {
                    socket.emit('collab_cancel_call', { target_sid: voiceCallTargetSid });
                } else {
                    socket.emit('collab_hangup', { target_sid: voiceCallTargetSid });
                }
                cleanupWebRTC();
                hideCallUI();
            }
        };

        let isMuted = false;
        document.getElementById('collabCallMuteBtn').onclick = () => {
            if (localStream) {
                isMuted = !isMuted;
                localStream.getAudioTracks().forEach(track => {
                    track.enabled = !isMuted;
                });
                const muteBtn = document.getElementById('collabCallMuteBtn');
                if (isMuted) {
                    muteBtn.className = 'w-11 h-11 rounded-full bg-red-600/20 hover:bg-red-600/30 text-red-500 flex items-center justify-center transition-all border border-red-500/30';
                    muteBtn.innerHTML = '<i class="fa-solid fa-microphone-slash text-sm"></i>';
                } else {
                    muteBtn.className = 'w-11 h-11 rounded-full bg-slate-800 hover:bg-slate-700 active:scale-95 text-slate-300 flex items-center justify-center transition-all border border-slate-700/50';
                    muteBtn.innerHTML = '<i class="fa-solid fa-microphone text-sm"></i>';
                }
            }
        };
    }

    function showCallUI(state, name, sid) {
        ensureCallUI();
        const widget = document.getElementById('collabCallWidget');
        const nameEl = document.getElementById('collabCallName');
        const avatarEl = document.getElementById('collabCallAvatar');
        const statusTextEl = document.getElementById('collabCallStatusText');
        const statusDotEl = document.getElementById('collabCallStatusDot');

        const acceptBtn = document.getElementById('collabCallAcceptBtn');
        const rejectBtn = document.getElementById('collabCallRejectBtn');
        const hangupBtn = document.getElementById('collabCallHangupBtn');
        const muteBtn = document.getElementById('collabCallMuteBtn');
        const timerEl = document.getElementById('collabActiveCallTimer');

        nameEl.textContent = name;

        const remoteUser = remoteUsers[sid] || {};
        const initials = name.slice(0, 2).toUpperCase();
        avatarEl.textContent = initials;
        avatarEl.style.backgroundColor = remoteUser.color || '#4f46e5';

        // Reset mute button
        muteBtn.className = 'w-11 h-11 rounded-full bg-slate-800 hover:bg-slate-700 active:scale-95 text-slate-300 flex items-center justify-center transition-all border border-slate-700/50';
        muteBtn.innerHTML = '<i class="fa-solid fa-microphone text-sm"></i>';

        widget.classList.remove('hidden');
        setTimeout(() => {
            widget.classList.remove('scale-95', 'opacity-0');
            widget.classList.add('scale-100', 'opacity-100');
        }, 10);

        if (state === 'ringing') {
            statusTextEl.textContent = 'Cuộc gọi đến...';
            statusDotEl.className = 'w-2.5 h-2.5 rounded-full bg-amber-500 animate-pulse';
            acceptBtn.classList.remove('hidden');
            rejectBtn.classList.remove('hidden');
            hangupBtn.classList.add('hidden');
            muteBtn.classList.add('hidden');
            timerEl.textContent = 'Đang đổ chuông';
        } else if (state === 'calling') {
            statusTextEl.textContent = 'Đang gọi...';
            statusDotEl.className = 'w-2.5 h-2.5 rounded-full bg-blue-500 animate-pulse';
            acceptBtn.classList.add('hidden');
            rejectBtn.classList.add('hidden');
            hangupBtn.classList.remove('hidden');
            muteBtn.classList.add('hidden');
            timerEl.textContent = 'Đang đổ chuông...';
        } else if (state === 'connected') {
            statusTextEl.textContent = 'Đang kết nối';
            statusDotEl.className = 'w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse';
            acceptBtn.classList.add('hidden');
            rejectBtn.classList.add('hidden');
            hangupBtn.classList.remove('hidden');
            muteBtn.classList.remove('hidden');

            startCallTimer();
        }
    }

    function hideCallUI() {
        const widget = document.getElementById('collabCallWidget');
        if (!widget) return;
        widget.classList.remove('scale-100', 'opacity-100');
        widget.classList.add('scale-95', 'opacity-0');
        setTimeout(() => {
            widget.classList.add('hidden');
        }, 300);
    }

    function ensureChatUI() {
        if (document.getElementById('collabChatModal')) return;

        // Add animations & extra styles
        const style = document.createElement('style');
        style.innerHTML = `
            @keyframes collab-slide-in {
                from { transform: translateY(0.5rem) scale(0.95); opacity: 0; }
                to { transform: translateY(0) scale(1); opacity: 1; }
            }
            @keyframes collab-toast-in {
                from { transform: translateX(2rem); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            .collab-toast-enter {
                animation: collab-toast-in 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;
            }
            .collab-modal-enter {
                animation: collab-slide-in 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;
            }
        `;
        document.head.appendChild(style);

        // 1. Create Notification Container if missing
        if (!document.getElementById('collabNotificationContainer')) {
            const notifContainer = document.createElement('div');
            notifContainer.id = 'collabNotificationContainer';
            notifContainer.className = 'fixed top-4 right-4 z-[9999] flex flex-col gap-3 pointer-events-none w-80';
            document.body.appendChild(notifContainer);
        }

        // 2. Create Chat Modal (Send message)
        const chatModal = document.createElement('div');
        chatModal.id = 'collabChatModal';
        chatModal.className = 'fixed inset-0 flex items-center justify-center z-[9999] hidden';
        chatModal.innerHTML = `
            <div class="absolute inset-0 bg-slate-950/60 backdrop-blur-sm transition-opacity" id="collabChatModalBackdrop"></div>
            <div class="bg-slate-900 border border-slate-700/50 rounded-xl shadow-2xl w-full max-w-sm overflow-hidden relative z-10 transform transition-all" id="collabChatModalContent">
                <div class="px-5 py-3 border-b border-slate-800 flex justify-between items-center bg-slate-950/40">
                    <h3 class="text-xs font-bold text-white flex items-center gap-2">
                        <i class="fa-regular fa-paper-plane text-blue-400"></i>
                        Gửi tin nhắn đến <span id="collabChatTargetName" class="text-blue-400">User</span>
                    </h3>
                    <button class="text-slate-400 hover:text-white transition-colors" id="collabChatCloseBtn">
                        <i class="fa-solid fa-xmark text-sm"></i>
                    </button>
                </div>
                <div class="p-5 space-y-4">
                    <textarea id="collabChatMessageInput" 
                              rows="3" 
                              class="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-white placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none resize-none transition-all"
                              placeholder="Nhập tin nhắn..."></textarea>
                    <div class="flex items-center gap-2 text-xs text-slate-300">
                        <input type="checkbox" id="collabChatSendAllCheck" class="rounded border-slate-700 bg-slate-800 text-blue-500 focus:ring-blue-500 focus:ring-offset-slate-900 cursor-pointer">
                        <label for="collabChatSendAllCheck" class="cursor-pointer select-none">Gửi tin nhắn cho tất cả</label>
                    </div>
                    <div class="flex justify-end gap-2 text-xs">
                        <button id="collabChatCancelBtn" class="px-5 py-1.5 bg-slate-850 hover:bg-slate-800 text-slate-300 font-semibold rounded-lg border border-slate-800 transition-all">Hủy</button>
                        <button id="collabChatSendBtn" class="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold rounded-lg transition-all flex items-center gap-1.5 shadow-lg shadow-blue-500/10">
                            Gửi <i class="fa-solid fa-chevron-right text-[10px]"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(chatModal);

        // 3. Create View Message Modal
        const viewModal = document.createElement('div');
        viewModal.id = 'collabViewMessageModal';
        viewModal.className = 'fixed inset-0 flex items-center justify-center z-[9999] hidden';
        viewModal.innerHTML = `
            <div class="absolute inset-0 bg-slate-950/60 backdrop-blur-sm transition-opacity" id="collabViewMessageModalBackdrop"></div>
            <div class="bg-slate-900 border border-slate-700/50 rounded-xl shadow-2xl w-full max-w-sm overflow-hidden relative z-10 transform transition-all" id="collabViewMessageModalContent">
                <div class="px-5 py-3 border-b border-slate-800 flex justify-between items-center bg-slate-950/40">
                    <h3 class="text-xs font-bold text-white flex items-center gap-2">
                        <i class="fa-regular fa-comment text-blue-400"></i>
                        Tin nhắn từ <span id="collabViewMessageSenderName" class="text-blue-400">User</span>
                    </h3>
                    <button class="text-slate-400 hover:text-white transition-colors" id="collabViewMessageCloseBtn">
                        <i class="fa-solid fa-xmark text-sm"></i>
                    </button>
                </div>
                <div class="p-5 space-y-4">
                    <div id="collabViewMessageContent" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-3.5 text-xs text-slate-200 whitespace-pre-wrap min-h-[60px]"></div>
                    <div class="flex justify-end gap-2 text-xs">
                        <button id="collabViewMessageReplyBtn" class="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold rounded-lg transition-all flex items-center gap-1.5 shadow-lg shadow-blue-500/10">
                            Trả lời <i class="fa-solid fa-reply text-[10px]"></i>
                        </button>
                        <button id="collabViewMessageOkBtn" class="px-3.5 py-1.5 bg-slate-850 hover:bg-slate-800 text-slate-300 font-semibold rounded-lg border border-slate-800 transition-all">Đóng</button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(viewModal);

        // Bind events for Chat Modal (Send)
        const closeChat = () => {
            const content = document.getElementById('collabChatModalContent');
            content.classList.remove('collab-modal-enter');
            chatModal.classList.add('hidden');
        };

        document.getElementById('collabChatCloseBtn').onclick = closeChat;
        document.getElementById('collabChatCancelBtn').onclick = closeChat;
        document.getElementById('collabChatModalBackdrop').onclick = closeChat;

        const sendMessage = () => {
            const input = document.getElementById('collabChatMessageInput');
            const message = input.value.trim();
            const sendAllCheck = document.getElementById('collabChatSendAllCheck');
            const isSendAll = sendAllCheck && sendAllCheck.checked;

            if (!message) return;
            if (!isSendAll && !activeChatSid) return;

            if (socket && socket.connected) {
                if (isSendAll) {
                    for (const sid in remoteUsers) {
                        socket.emit('send_direct_message', {
                            target_sid: sid,
                            message: message
                        });
                    }
                    showToastSent('Tất cả mọi người');
                } else {
                    socket.emit('send_direct_message', {
                        target_sid: activeChatSid,
                        message: message
                    });
                    showToastSent(activeChatUserName);
                }
            }
            closeChat();
        };

        document.getElementById('collabChatSendBtn').onclick = sendMessage;
        document.getElementById('collabChatMessageInput').onkeydown = (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        };

        const sendAllCheck = document.getElementById('collabChatSendAllCheck');
        if (sendAllCheck) {
            sendAllCheck.onchange = (e) => {
                const targetNameSpan = document.getElementById('collabChatTargetName');
                if (e.target.checked) {
                    targetNameSpan.textContent = 'Tất cả mọi người';
                } else {
                    targetNameSpan.textContent = activeChatUserName || 'User';
                }
            };
        }

        // Bind events for View Message Modal
        const closeViewMessage = () => {
            viewModal.classList.add('hidden');
        };

        document.getElementById('collabViewMessageCloseBtn').onclick = closeViewMessage;
        document.getElementById('collabViewMessageOkBtn').onclick = closeViewMessage;
        document.getElementById('collabViewMessageModalBackdrop').onclick = closeViewMessage;

        let currentSenderSid = null;
        let currentSenderName = null;

        window.openViewMessage = (senderSid, senderName, message) => {
            currentSenderSid = senderSid;
            currentSenderName = senderName;
            document.getElementById('collabViewMessageSenderName').textContent = senderName;
            document.getElementById('collabViewMessageContent').textContent = message;

            const replyBtn = document.getElementById('collabViewMessageReplyBtn');
            if (remoteUsers[senderSid]) {
                replyBtn.style.display = 'inline-flex';
            } else {
                replyBtn.style.display = 'none';
            }

            viewModal.classList.remove('hidden');
            const content = document.getElementById('collabViewMessageModalContent');
            content.classList.add('collab-modal-enter');
        };

        document.getElementById('collabViewMessageReplyBtn').onclick = () => {
            closeViewMessage();
            if (currentSenderSid && remoteUsers[currentSenderSid]) {
                setTimeout(() => {
                    openChatWithUser(currentSenderSid, remoteUsers[currentSenderSid]);
                }, 200);
            }
        };
    }

    function openChatWithUser(sid, user) {
        ensureChatUI();
        activeChatSid = sid;
        activeChatUserName = user.user_name || 'User';
        document.getElementById('collabChatTargetName').textContent = activeChatUserName;
        document.getElementById('collabChatMessageInput').value = '';

        const sendAllCheck = document.getElementById('collabChatSendAllCheck');
        if (sendAllCheck) {
            sendAllCheck.checked = false;
        }

        const chatModal = document.getElementById('collabChatModal');
        chatModal.classList.remove('hidden');
        const content = document.getElementById('collabChatModalContent');
        content.classList.add('collab-modal-enter');
        document.getElementById('collabChatMessageInput').focus();
    }

    function showToastSent(targetName) {
        const notifContainer = document.getElementById('collabNotificationContainer');
        if (!notifContainer) return;

        const toast = document.createElement('div');
        toast.className = 'collab-toast-enter pointer-events-auto bg-slate-900/95 border border-emerald-500/30 rounded-xl shadow-xl p-3 flex gap-2.5 items-center backdrop-blur-md w-72';
        toast.innerHTML = `
            <div class="flex-shrink-0 w-6 h-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center">
                <i class="fa-solid fa-check text-xs"></i>
            </div>
            <div class="flex-1 text-[11px] text-left">
                <span class="text-slate-400">Đã gửi tin nhắn đến</span>
                <span class="font-bold text-white ml-1">${targetName}</span>
            </div>
        `;
        notifContainer.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-10px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    function showNotificationToast(senderSid, senderName, message) {
        ensureChatUI();
        playNotificationSound();
        const notifContainer = document.getElementById('collabNotificationContainer');
        if (!notifContainer) return;

        const toast = document.createElement('div');
        toast.className = 'collab-toast-enter pointer-events-auto bg-slate-900 border border-slate-700/50 rounded-xl shadow-2xl p-4 flex gap-3 cursor-pointer hover:border-blue-500/50 transition-all duration-200 transform hover:scale-[1.02] active:scale-95 bg-slate-950/80 backdrop-blur-md';

        toast.innerHTML = `
            <div class="flex-shrink-0 w-8 h-8 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center">
                <i class="fa-regular fa-comment-dots text-sm"></i>
            </div>
            <div class="flex-1 space-y-1 text-left">
                <div class="text-[10px] text-blue-400 font-bold uppercase tracking-wider">Tin nhắn mới</div>
                <div class="text-xs font-bold text-white">Từ: <span class="text-blue-300 font-bold">${senderName}</span></div>
                <div class="text-[11px] text-slate-400 line-clamp-2">${message}</div>
            </div>
        `;

        toast.onclick = () => {
            toast.remove();
            openViewMessage(senderSid, senderName, message);
        };

        notifContainer.appendChild(toast);

        setTimeout(() => {
            if (toast.parentNode) {
                toast.style.opacity = '0';
                toast.style.transform = 'translateX(20px)';
                toast.style.transition = 'all 0.3s ease';
                setTimeout(() => toast.remove(), 300);
            }
        }, 8000);
    }

    // 2. Initialize UI Badge
    function initUI() {
        const collabUserName = document.getElementById('collabUserName');
        const collabUserNameBadge = document.getElementById('collabUserNameBadge');

        if (collabUserName) collabUserName.textContent = myName;
        if (collabUserNameBadge) {
            collabUserNameBadge.style.borderColor = myColor + '60'; // translucent border
            collabUserNameBadge.style.backgroundColor = myColor + '10'; // subtle bg tint

            // Allow changing name on click
            collabUserNameBadge.onclick = () => {
                const newName = prompt('Nhập tên hiển thị mới của bạn:', myName);
                if (newName && newName.trim() && newName.trim() !== myName) {
                    myName = newName.trim();
                    localStorage.setItem('collab_username', myName);
                    collabUserName.textContent = myName;

                    // Reconnect or update state on server
                    if (socket && socket.connected) {
                        socket.disconnect();
                        socket.connect();
                    }
                }
            };
        }

        // Add style for tooltips/cursor if needed
        if (!document.getElementById('collab-styles')) {
            const style = document.createElement('style');
            style.id = 'collab-styles';
            style.innerHTML = `
                .collab-tooltip::after {
                    content: "";
                    position: absolute;
                    top: 100%;
                    left: 50%;
                    margin-left: -5px;
                    border-width: 5px;
                    border-style: solid;
                    border-color: rgba(15, 23, 42, 0.95) transparent transparent transparent;
                }
            `;
            document.head.appendChild(style);
        }

        // Initialize Chat UI
        ensureChatUI();
        ensureCallUI();

        // Initialize Users Modal UI
        const btnCollabUsersModal = document.getElementById('btnCollabUsersModal');
        const collabUsersModalWrapper = document.getElementById('collabUsersModalWrapper');
        const closeCollabUsersModal = document.getElementById('closeCollabUsersModal');

        if (btnCollabUsersModal && collabUsersModalWrapper && closeCollabUsersModal) {
            btnCollabUsersModal.addEventListener('click', () => {
                collabUsersModalWrapper.classList.remove('hidden');
            });
            closeCollabUsersModal.addEventListener('click', () => {
                collabUsersModalWrapper.classList.add('hidden');
            });
            collabUsersModalWrapper.addEventListener('click', (e) => {
                if (e.target === collabUsersModalWrapper) {
                    collabUsersModalWrapper.classList.add('hidden');
                }
            });
        }
    }

    // 3. Connect Socket.IO
    function connectSocket() {
        if (typeof io === 'undefined') {
            console.warn('[Collab] Socket.IO client library not loaded.');
            return;
        }

        socket = io();
        window.collabSocket = socket;

        const indicator = document.getElementById('collabUserIndicator');

        socket.on('connect', () => {
            console.log('[Collab] Connected with SID:', socket.id);
            if (indicator) {
                indicator.className = 'w-2.5 h-2.5 rounded-full bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)] animate-pulse';
            }

            // Join project room
            socket.emit('join_project', {
                project_id: PROJECT_ID,
                user_name: myName,
                color: myColor
            });

            // Send initial image state if we already have one
            const currentImgId = (typeof currentImage !== 'undefined' && currentImage) ? currentImage.id : null;
            if (currentImgId) {
                sendMyState(undefined, undefined, currentImgId);
            }
        });

        socket.on('disconnect', () => {
            console.log('[Collab] Disconnected');
            if (indicator) {
                indicator.className = 'w-2.5 h-2.5 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.6)]';
            }
            clearAllCursors();
            remoteUsers = {};
            updateUsersList();

            if (voiceCallState !== 'idle') {
                cleanupWebRTC();
                hideCallUI();
            }
        });

        // Collaboration events
        socket.on('init_users', (users) => {
            console.log('[Collab] Active users:', users);
            remoteUsers = users;
            // Initialize targets
            for (const sid in remoteUsers) {
                remoteUsers[sid].targetX = remoteUsers[sid].x;
                remoteUsers[sid].targetY = remoteUsers[sid].y;
            }
            updateUsersList();
        });

        socket.on('user_joined', (data) => {
            console.log('[Collab] User joined:', data);
            remoteUsers[data.sid] = data.user_info;
            remoteUsers[data.sid].targetX = data.user_info.x;
            remoteUsers[data.sid].targetY = data.user_info.y;
            updateUsersList();
        });

        socket.on('user_disconnected', (data) => {
            console.log('[Collab] User left:', data.sid);
            if (data.sid === voiceCallTargetSid) {
                showToastInfo("Đối phương đã ngắt kết nối.");
                cleanupWebRTC();
                hideCallUI();
            }
            if (remoteUsers[data.sid]) {
                delete remoteUsers[data.sid];
                const cursorEl = document.getElementById(`collab-cursor-${data.sid}`);
                if (cursorEl) cursorEl.remove();
                const highlightEl = document.getElementById(`collab-highlight-${data.sid}`);
                if (highlightEl) highlightEl.remove();
                updateUsersList();
            }
        });

        socket.on('state_updated', (data) => {
            const sid = data.sid;
            if (remoteUsers[sid]) {
                const imgChanged = remoteUsers[sid].image_id !== data.image_id;

                remoteUsers[sid].targetX = data.x;
                remoteUsers[sid].targetY = data.y;
                if (remoteUsers[sid].currentX === undefined) {
                    remoteUsers[sid].currentX = data.x;
                    remoteUsers[sid].currentY = data.y;
                }

                remoteUsers[sid].image_id = data.image_id;
                remoteUsers[sid].active_box_id = data.active_box_id;

                if (imgChanged) {
                    updateUsersList();
                }
            }
        });

        socket.on('box_created', (data) => {
            const currentImageId = (typeof currentImage !== 'undefined' && currentImage) ? currentImage.id : null;
            if (data.image_id === currentImageId && typeof editor !== 'undefined' && editor) {
                editor.addBoxToCanvas(
                    data.box.class_id,
                    data.box.x,
                    data.box.y,
                    data.box.w,
                    data.box.h,
                    false, // isNew = false
                    false, // isOverlapping
                    data.box.collabId
                );
            }
        });

        socket.on('box_updated', (data) => {
            const currentImageId = (typeof currentImage !== 'undefined' && currentImage) ? currentImage.id : null;
            if (data.image_id === currentImageId && typeof editor !== 'undefined' && editor && editor.canvas) {
                const rects = editor.canvas.getObjects('rect');
                const box = rects.find(r => r.collabId === data.collabId);
                if (box) {
                    if (data.class_id !== undefined && data.class_id !== box.classId) {
                        box.classId = data.class_id;
                        const cls = editor.classes.find(c => c.id === data.class_id) || { color: 'white', name: 'Unknown' };

                        if (box.__labelTag) {
                            box.__labelTag.set('fill', cls.color);
                        }
                        if (box.__labelText) {
                            box.__labelText.set('text', cls.name);
                        }
                    }

                    box.set({
                        left: data.left !== undefined ? data.left : box.left,
                        top: data.top !== undefined ? data.top : box.top,
                        scaleX: data.scaleX !== undefined ? data.scaleX : box.scaleX,
                        scaleY: data.scaleY !== undefined ? data.scaleY : box.scaleY,
                        width: data.width !== undefined ? data.width : box.width,
                        height: data.height !== undefined ? data.height : box.height
                    });

                    // Temporarily lock/highlight it to show it is being edited
                    box.set({ stroke: 'orange' });

                    box.setCoords();
                    editor.canvas.requestRenderAll();

                    // Reset stroke color after a short delay
                    if (box._updateTimer) clearTimeout(box._updateTimer);
                    box._updateTimer = setTimeout(() => {
                        const cls = editor.classes.find(c => c.id === box.classId) || { color: 'white' };
                        box.set('stroke', cls.color);
                        editor.canvas.requestRenderAll();
                    }, 500);
                }
            }
        });

        socket.on('box_deleted', (data) => {
            const currentImageId = (typeof currentImage !== 'undefined' && currentImage) ? currentImage.id : null;
            if (data.image_id === currentImageId && typeof editor !== 'undefined' && editor && editor.canvas) {
                const rects = editor.canvas.getObjects('rect');
                const box = rects.find(r => r.collabId === data.collabId);
                if (box) {
                    editor.canvas.remove(box);
                    editor.canvas.requestRenderAll();
                }
            }
        });

        socket.on('box_lock', (data) => {
            const currentImageId = (typeof currentImage !== 'undefined' && currentImage) ? currentImage.id : null;
            if (data.image_id === currentImageId && typeof editor !== 'undefined' && editor && editor.canvas) {
                const rects = editor.canvas.getObjects('rect');
                const box = rects.find(r => r.collabId === data.collabId);
                if (box) {
                    const activeObjects = editor.canvas.getActiveObjects();
                    if (activeObjects && activeObjects.includes(box)) {
                        editor.canvas.discardActiveObject();
                        // Triggers selection:cleared which handles UI
                    }
                    box.set({
                        selectable: false,
                        evented: false,
                        strokeDashArray: [5, 5],
                        opacity: 0.5
                    });
                    box._lockedBy = data.sid;
                    editor.canvas.requestRenderAll();
                }
            }
        });

        socket.on('box_unlock', (data) => {
            const currentImageId = (typeof currentImage !== 'undefined' && currentImage) ? currentImage.id : null;
            if (data.image_id === currentImageId && typeof editor !== 'undefined' && editor && editor.canvas) {
                const rects = editor.canvas.getObjects('rect');
                const box = rects.find(r => r.collabId === data.collabId);
                if (box) {
                    box.set({
                        selectable: editor.showBoxes && (editor.currentMode === 'select'),
                        evented: editor.showBoxes,
                        strokeDashArray: null,
                        opacity: 1
                    });
                    box._lockedBy = null;
                    editor.canvas.requestRenderAll();
                }
            }
        });

        socket.on('sync_requested', (data) => {
            const currentImageId = (typeof currentImage !== 'undefined' && currentImage) ? currentImage.id : null;
            if (data.image_id === currentImageId && typeof editor !== 'undefined' && editor && editor.canvas) {
                // Check if we actually have unsaved changes or if we just have boxes loaded
                // To be safe, we just send all current boxes.
                const boxes = editor.canvas.getObjects('rect').map(obj => {
                    return {
                        collabId: obj.collabId,
                        class_id: obj.classId,
                        left: obj.left,
                        top: obj.top,
                        scaleX: obj.scaleX,
                        scaleY: obj.scaleY,
                        width: obj.width,
                        height: obj.height
                    };
                });
                socket.emit('sync_response', {
                    target_sid: data.requester_sid,
                    image_id: currentImageId,
                    boxes: boxes
                });
            }
        });

        socket.on('sync_received', (data) => {
            const currentImageId = (typeof currentImage !== 'undefined' && currentImage) ? currentImage.id : null;
            if (data.image_id === currentImageId && typeof editor !== 'undefined' && editor && editor.canvas) {
                if (!data.boxes || data.boxes.length === 0) return;

                const currentRects = editor.canvas.getObjects('rect');

                let changed = false;
                data.boxes.forEach(b => {
                    const existing = currentRects.find(r => r.collabId === b.collabId);
                    if (existing) {
                        existing.set({
                            left: b.left,
                            top: b.top,
                            scaleX: b.scaleX,
                            scaleY: b.scaleY,
                            width: b.width,
                            height: b.height
                        });
                        existing.setCoords();
                        changed = true;
                    } else {
                        const scaleX = b.scaleX || 1;
                        const scaleY = b.scaleY || 1;
                        const w = (b.width * scaleX) / editor.imageWidth;
                        const h = (b.height * scaleY) / editor.imageHeight;
                        const x = (b.left + (b.width * scaleX) / 2) / editor.imageWidth;
                        const y = (b.top + (b.height * scaleY) / 2) / editor.imageHeight;

                        editor.addBoxToCanvas(
                            b.class_id,
                            x,
                            y,
                            w,
                            h,
                            false, // isNew
                            false, // isOverlapping
                            b.collabId
                        );
                        changed = true;
                    }
                });

                // We shouldn't aggressively delete boxes just because one user doesn't have them
                // unless we implement a strict master-slave logic. Let's just merge them.
                if (changed) {
                    editor.canvas.requestRenderAll();
                }
            }
        });

        socket.on('receive_direct_message', (data) => {
            showNotificationToast(data.sender_sid, data.sender_name, data.message);
        });

        socket.on('collab_incoming_call', (data) => {
            if (voiceCallState !== 'idle') {
                socket.emit('collab_reject_call', { target_sid: data.caller_sid });
                return;
            }
            voiceCallTargetSid = data.caller_sid;
            voiceCallState = 'ringing';

            showCallUI('ringing', data.caller_name, data.caller_sid);
            startIncomingRingtone();
        });

        socket.on('collab_call_cancelled', () => {
            showToastInfo("Cuộc gọi bị hủy bởi người gọi.");
            cleanupWebRTC();
            hideCallUI();
        });

        socket.on('collab_call_accepted', (data) => {
            stopOutgoingRingtone();
            showCallUI('connected', remoteUsers[data.target_sid]?.user_name || 'User', data.target_sid);
            startWebRTCCall(data.target_sid);
        });

        socket.on('collab_call_rejected', (data) => {
            showToastInfo("Cuộc gọi bị từ chối.");
            cleanupWebRTC();
            hideCallUI();
        });

        socket.on('collab_wertc_signal', async (data) => {
            const { sender_sid, signal } = data;
            if (sender_sid !== voiceCallTargetSid) return;

            try {
                if (signal.type === 'offer') {
                    if (!peerConnection) {
                        peerConnection = new RTCPeerConnection(rtcConfig);

                        localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                        localStream.getTracks().forEach(track => {
                            peerConnection.addTrack(track, localStream);
                        });

                        peerConnection.ontrack = (event) => {
                            console.log('[Collab] Received remote track');
                            playRemoteStream(event.streams[0]);
                        };

                        peerConnection.onicecandidate = (event) => {
                            if (event.candidate && socket && socket.connected) {
                                socket.emit('collab_wertc_signal', {
                                    target_sid: sender_sid,
                                    signal: { type: 'candidate', candidate: event.candidate }
                                });
                            }
                        };
                    }

                    await peerConnection.setRemoteDescription(new RTCSessionDescription({ type: 'offer', sdp: signal.sdp }));
                    const answer = await peerConnection.createAnswer();
                    await peerConnection.setLocalDescription(answer);
                    socket.emit('collab_wertc_signal', {
                        target_sid: sender_sid,
                        signal: { type: 'answer', sdp: answer.sdp }
                    });

                    while (remoteCandidateQueue.length > 0) {
                        const cand = remoteCandidateQueue.shift();
                        await peerConnection.addIceCandidate(new RTCIceCandidate(cand));
                    }
                } else if (signal.type === 'answer') {
                    if (peerConnection) {
                        await peerConnection.setRemoteDescription(new RTCSessionDescription({ type: 'answer', sdp: signal.sdp }));
                        while (remoteCandidateQueue.length > 0) {
                            const cand = remoteCandidateQueue.shift();
                            await peerConnection.addIceCandidate(new RTCIceCandidate(cand));
                        }
                    }
                } else if (signal.type === 'candidate') {
                    if (peerConnection && peerConnection.remoteDescription && peerConnection.remoteDescription.type) {
                        await peerConnection.addIceCandidate(new RTCIceCandidate(signal.candidate));
                    } else {
                        remoteCandidateQueue.push(signal.candidate);
                    }
                }
            } catch (err) {
                console.error('[Collab] Error handling WebRTC signal:', err);
            }
        });

        socket.on('collab_call_hungup', () => {
            showToastInfo("Cuộc gọi đã kết thúc.");
            cleanupWebRTC();
            hideCallUI();
        });

        socket.on('annotations_changed', (data) => {
            if (typeof currentWorkspace !== 'undefined' && currentWorkspace.allImages) {
                const img = currentWorkspace.allImages.find(i => i.id === data.image_id);
                if (img) {
                    img.is_labeled = data.is_labeled;
                    if (data.classes) {
                        img.classes = data.classes;
                    }

                    const el = document.getElementById(`img-${data.image_id}`);
                    if (el) {
                        const iconContainer = el.querySelector('.flex.items-center.gap-2');
                        if (iconContainer) {
                            let checkIcon = iconContainer.querySelector('.fa-check') || iconContainer.querySelector('.fa-circle');
                            if (!checkIcon) {
                                iconContainer.insertAdjacentHTML('beforeend', '<i class="fa-regular fa-circle text-content-muted"></i>');
                                checkIcon = iconContainer.querySelector('.fa-circle');
                            }
                            if (checkIcon) {
                                if (data.is_labeled) {
                                    checkIcon.className = 'fa-solid fa-check text-secondary';
                                } else {
                                    checkIcon.className = 'fa-regular fa-circle text-content-muted';
                                }
                            }
                        }
                    }

                    // AUTO-RELOAD: If the user is currently viewing this image,
                    // reload the latest boxes from the server to keep canvas in sync
                    const currentImageId = (typeof currentImage !== 'undefined' && currentImage) ? currentImage.id : null;
                    if (data.image_id === currentImageId && typeof editor !== 'undefined' && editor && editor.canvas) {
                        // Only reload if the editor is not currently dirty (user has unsaved local changes)
                        if (!editor.isDirty) {
                            (async () => {
                                try {
                                    const labels = await API.getLabel(data.image_id);
                                    // Guard: make sure user is still on the same image
                                    const stillSameImage = (typeof currentImage !== 'undefined' && currentImage && currentImage.id === data.image_id);
                                    if (stillSameImage && labels) {
                                        editor.loadBoxes(labels);
                                        console.log(`[Collab] Auto-reloaded ${labels.length} boxes for image ${data.image_id} after remote save.`);
                                    }
                                } catch (err) {
                                    console.error('[Collab] Error auto-reloading boxes after annotations_changed:', err);
                                }
                            })();
                        } else {
                            console.log(`[Collab] Skipped auto-reload for image ${data.image_id} — local editor has unsaved changes.`);
                        }
                    }
                }
            }
        });
    }

    // 4. Update Cursors on Canvas (Interpolated Loop)
    function updateCursorsLoop(timestamp) {
        requestAnimationFrame(updateCursorsLoop);

        if (typeof editor === 'undefined' || !editor || !editor.canvas) return;

        const container = editor.canvas.getElement().parentNode; // .canvas-container
        if (!container) return;

        const currentImageId = (typeof currentImage !== 'undefined' && currentImage) ? currentImage.id : null;
        const rects = editor.canvas.getObjects('rect');
        const vpt = editor.canvas.viewportTransform;

        for (const [sid, user] of Object.entries(remoteUsers)) {
            let cursorEl = document.getElementById(`collab-cursor-${sid}`);
            let highlightEl = document.getElementById(`collab-highlight-${sid}`);

            // Only display cursor if they are on the same image
            if (user.image_id === currentImageId && currentImageId !== null) {
                if (!cursorEl) {
                    cursorEl = createCursorElement(sid, user);
                    container.appendChild(cursorEl);
                }

                // Initialize current position if missing
                if (user.currentX === undefined) user.currentX = user.targetX !== undefined ? user.targetX : user.x;
                if (user.currentY === undefined) user.currentY = user.targetY !== undefined ? user.targetY : user.y;

                // Fallback targets if missing
                if (user.targetX === undefined) user.targetX = user.x;
                if (user.targetY === undefined) user.targetY = user.y;

                // Linear Interpolation (LERP) for smooth movement
                user.currentX += (user.targetX - user.currentX) * 0.3;
                user.currentY += (user.targetY - user.currentY) * 0.3;

                // Transform image-space coords (x,y) to viewport screen coords
                if (vpt) {
                    const screenPoint = fabric.util.transformPoint({ x: user.currentX, y: user.currentY }, vpt);
                    cursorEl.style.transform = `translate3d(${screenPoint.x - 2}px, ${screenPoint.y - 2}px, 0)`;
                    cursorEl.style.display = 'block';
                }

                // Active Box Highlight
                if (user.active_box_id) {
                    if (!highlightEl) {
                        highlightEl = document.createElement('div');
                        highlightEl.id = `collab-highlight-${sid}`;
                        highlightEl.className = 'absolute left-0 top-0 pointer-events-none border-2 z-[400] shadow-[0_0_8px_rgba(0,0,0,0.5)] transition-all duration-100 origin-top-left';
                        // Add a small label above the box
                        highlightEl.innerHTML = `<div class="absolute -top-5 left-0 px-1 text-[10px] text-white font-bold rounded shadow" style="background-color: ${user.color}; white-space: nowrap;">${user.user_name} focusing</div>`;
                        container.appendChild(highlightEl);
                    }

                    const box = rects.find(r => r.collabId === user.active_box_id);
                    if (box && vpt) {
                        // calculate bounding box in screen coords
                        const w = box.width * box.scaleX * vpt[0];
                        const h = box.height * box.scaleY * vpt[3];
                        const left = box.left * vpt[0] + vpt[4];
                        const top = box.top * vpt[3] + vpt[5];

                        highlightEl.style.transform = `translate3d(${left}px, ${top}px, 0)`;
                        highlightEl.style.width = `${w}px`;
                        highlightEl.style.height = `${h}px`;
                        highlightEl.style.borderColor = user.color;
                        highlightEl.style.display = 'block';
                    } else {
                        if (highlightEl) highlightEl.style.display = 'none';
                    }
                } else {
                    if (highlightEl) highlightEl.style.display = 'none';
                }

            } else {
                if (cursorEl) {
                    cursorEl.style.display = 'none';
                }
                if (highlightEl) {
                    highlightEl.style.display = 'none';
                }
            }
        }
    }

    function createCursorElement(sid, user) {
        const cursor = document.createElement('div');
        cursor.id = `collab-cursor-${sid}`;
        cursor.className = 'absolute left-0 top-0 pointer-events-none z-[1000] select-none';
        cursor.style.transform = 'translate3d(-2px, -2px, 0)';

        // Custom colored SVG pointer + name tag
        cursor.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="filter: drop-shadow(0px 1px 2px rgba(0,0,0,0.4));">
                <path d="M4.5 3V19.5L9.3 14.7L15.3 20.7L18.3 17.7L12.3 11.7H18.3L4.5 3Z" fill="${user.color}" stroke="white" stroke-width="2" stroke-linejoin="round"/>
            </svg>
            <div class="absolute left-4 top-4 px-2 py-0.5 rounded text-[10px] font-bold text-white shadow-md whitespace-nowrap z-50 pointer-events-none" style="background-color: ${user.color}">
                ${user.user_name}
            </div>
        `;
        return cursor;
    }

    function clearAllCursors() {
        document.querySelectorAll('[id^="collab-cursor-"]').forEach(el => el.remove());
        document.querySelectorAll('[id^="collab-highlight-"]').forEach(el => el.remove());
    }

    function triggerVoiceCall(targetSid, targetUser) {
        if (voiceCallState !== 'idle') {
            showToastError("Bạn đang có một cuộc gọi khác.");
            return;
        }
        voiceCallTargetSid = targetSid;
        voiceCallState = 'calling';

        showCallUI('calling', targetUser.user_name || 'User', targetSid);
        startOutgoingRingtone();

        socket.emit('collab_call_user', { target_sid: targetSid });
    }

    function showAvatarContextMenu(e, sid, user) {
        e.preventDefault();
        e.stopPropagation();

        // Remove existing context menu if any
        const existingMenu = document.getElementById('collabAvatarContextMenu');
        if (existingMenu) existingMenu.remove();

        const menu = document.createElement('div');
        menu.id = 'collabAvatarContextMenu';
        menu.className = 'fixed bg-slate-900/95 backdrop-blur-md border border-slate-700/50 rounded-xl shadow-2xl py-1.5 w-36 text-white z-[99999] text-[11px] flex flex-col transition-all duration-150 transform scale-95 opacity-0';
        menu.style.zIndex = '99999';

        // Calculate safe position
        let x = e.clientX;
        let y = e.clientY;
        const menuWidth = 144; // w-36 = 144px
        const menuHeight = 76; // approximate height for 2 items

        if (x + menuWidth > window.innerWidth) {
            x = window.innerWidth - menuWidth - 8;
        }
        if (y + menuHeight > window.innerHeight) {
            y = window.innerHeight - menuHeight - 8;
        }

        menu.style.left = `${x}px`;
        menu.style.top = `${y}px`;

        menu.innerHTML = `
            <button id="ctxMenuChatBtn" class="w-full text-left px-3 py-2 hover:bg-slate-800 transition-colors flex items-center gap-2 text-slate-300 hover:text-white font-medium">
                <i class="fa-regular fa-comment text-blue-400 w-4 text-center"></i> Nhắn tin
            </button>
            <button id="ctxMenuCallBtn" class="w-full text-left px-3 py-2 hover:bg-slate-800 transition-colors flex items-center gap-2 text-slate-300 hover:text-white font-medium">
                <i class="fa-solid fa-phone text-emerald-400 w-4 text-center"></i> Gọi thoại
            </button>
        `;

        document.body.appendChild(menu);

        // Force reflow and animate in
        menu.getBoundingClientRect();
        menu.classList.remove('scale-95', 'opacity-0');
        menu.classList.add('scale-100', 'opacity-100');

        menu.querySelector('#ctxMenuChatBtn').onclick = () => {
            openChatWithUser(sid, user);
            menu.remove();
        };

        menu.querySelector('#ctxMenuCallBtn').onclick = () => {
            triggerVoiceCall(sid, user);
            menu.remove();
        };

        // Close menu on clicking outside
        const closeMenu = (event) => {
            if (!menu.contains(event.target)) {
                menu.remove();
                document.removeEventListener('click', closeMenu);
                document.removeEventListener('contextmenu', closeMenu);
            }
        };

        setTimeout(() => {
            document.addEventListener('click', closeMenu);
            document.addEventListener('contextmenu', closeMenu);
        }, 50);
    }

    // 5. Update Online Users Avatar List in Modal
    function updateUsersList() {
        const listEl = document.getElementById('collabUsersList');
        const emptyState = document.getElementById('collabUsersEmpty');
        const countBadge = document.getElementById('collabUsersCount');
        const modalCount = document.getElementById('collabUsersModalCount');

        if (!listEl) return;

        listEl.innerHTML = '';

        const currentImageId = (typeof currentImage !== 'undefined' && currentImage) ? currentImage.id : null;

        const userIds = Object.keys(remoteUsers);
        const userCount = userIds.length;

        // Update counts
        if (countBadge) {
            countBadge.textContent = userCount;
            if (userCount > 0) {
                countBadge.classList.remove('hidden');
            } else {
                countBadge.classList.add('hidden');
            }
        }
        if (modalCount) modalCount.textContent = userCount;

        // Update empty state
        if (emptyState) {
            if (userCount === 0) {
                emptyState.classList.remove('hidden');
            } else {
                emptyState.classList.add('hidden');
            }
        }

        for (const [sid, user] of Object.entries(remoteUsers)) {
            const initials = user.user_name ? user.user_name.slice(0, 2).toUpperCase() : '??';

            const listItem = document.createElement('div');
            listItem.className = 'flex items-center gap-3 p-2 hover:bg-panel rounded-lg cursor-pointer transition-colors group';

            const avatar = document.createElement('div');
            const isSameImage = user.image_id === currentImageId && currentImageId !== null;

            avatar.className = `w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-[11px] font-bold text-white shadow-sm border select-none transition-all relative`;
            avatar.style.backgroundColor = user.color;

            if (isSameImage) {
                avatar.style.borderColor = user.color;
                avatar.classList.add('ring-2', 'ring-offset-1', 'ring-offset-surface');
                avatar.style.setProperty('--tw-ring-color', user.color);
            } else {
                avatar.style.borderColor = 'rgba(255,255,255,0.2)';
            }
            avatar.textContent = initials;

            const infoDiv = document.createElement('div');
            infoDiv.className = 'flex flex-col flex-grow min-w-0';

            const nameEl = document.createElement('div');
            nameEl.className = 'text-sm font-semibold text-content truncate';
            nameEl.textContent = user.user_name;

            const statusEl = document.createElement('div');
            statusEl.className = 'text-xs truncate ' + (isSameImage ? 'text-green-400 font-medium' : 'text-content-muted');

            if (isSameImage) {
                statusEl.innerHTML = '<i class="fa-solid fa-location-dot mr-1"></i>Đang xem cùng ảnh';
            } else if (user.image_id) {
                statusEl.textContent = 'Đang xem ảnh khác';
            } else {
                statusEl.textContent = 'Đang ở phòng chờ';
            }

            infoDiv.appendChild(nameEl);
            infoDiv.appendChild(statusEl);

            const actionIcon = document.createElement('div');
            actionIcon.className = 'text-content-muted opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0';
            actionIcon.innerHTML = isSameImage ? '<i class="fa-solid fa-phone"></i>' : '<i class="fa-solid fa-image"></i>';

            listItem.appendChild(avatar);
            listItem.appendChild(infoDiv);
            listItem.appendChild(actionIcon);

            // Left click behavior: call user if same image, else navigate to image
            listItem.addEventListener('click', () => {
                if (isSameImage) {
                    triggerVoiceCall(sid, user);
                    // Hide modal after action
                    document.getElementById('collabUsersModalWrapper')?.classList.add('hidden');
                } else {
                    if (user.image_id) {
                        if (typeof currentWorkspace !== 'undefined' && currentWorkspace.allImages) {
                            const targetImg = currentWorkspace.allImages.find(img => String(img.id) === String(user.image_id));
                            if (targetImg) {
                                currentWorkspace.selectImage(targetImg);
                                document.getElementById('collabUsersModalWrapper')?.classList.add('hidden');
                            } else {
                                console.warn('[Collab] Target image not found in workspace list:', user.image_id);
                            }
                        }
                    } else {
                        showToastInfo(`${user.user_name} đang ở phòng chờ.`);
                    }
                }
            });

            // Right click to show custom context menu
            listItem.addEventListener('contextmenu', (e) => {
                showAvatarContextMenu(e, sid, user);
            });

            listEl.appendChild(listItem);
        }
    }

    // 6. Send State Updates to Server (Throttled)
    function sendMyState(x, y, imageId, activeBoxId) {
        if (!socket || !socket.connected) return;

        const payload = {};
        let changed = false;

        if (x !== undefined && x !== lastSentState.x) {
            payload.x = x;
            lastSentState.x = x;
            changed = true;
        }
        if (y !== undefined && y !== lastSentState.y) {
            payload.y = y;
            lastSentState.y = y;
            changed = true;
        }

        const targetImageId = imageId !== undefined ? imageId : ((typeof currentImage !== 'undefined' && currentImage) ? currentImage.id : null);
        if (targetImageId !== lastSentState.image_id) {
            payload.image_id = targetImageId;
            lastSentState.image_id = targetImageId;
            changed = true;
        }

        if (activeBoxId !== undefined && activeBoxId !== lastSentState.active_box_id) {
            payload.active_box_id = activeBoxId;
            lastSentState.active_box_id = activeBoxId;
            changed = true;
        }

        if (changed) {
            socket.emit('update_state', payload);
        }
    }

    function handleCanvasMouseMove(opt) {
        const now = Date.now();
        if (now - lastMoveTime < 150) return; // throttle to ~6.6 updates per second max
        lastMoveTime = now;

        if (typeof editor === 'undefined' || !editor || !editor.canvas) return;

        const pointer = editor.canvas.getPointer(opt.e);
        if (pointer) {
            sendMyState(Math.round(pointer.x), Math.round(pointer.y));
        }
    }

    // 7. Bind Events once Editor is initialized
    function bindCanvasListeners() {
        if (typeof editor !== 'undefined' && editor && editor.canvas) {
            editor.canvas.on('mouse:move', handleCanvasMouseMove);
            console.log('[Collab] Successfully bound to canvas events');
        } else {
            setTimeout(bindCanvasListeners, 100);
        }
    }

    // Hook into image switching
    window.updateMyImageId = (imageId) => {
        sendMyState(undefined, undefined, imageId, null);
        updateUsersList();
    };

    window.updateMyActiveBox = (boxId) => {
        sendMyState(undefined, undefined, undefined, boxId);
    };

    // 8. Run on DOMContentLoaded
    document.addEventListener('DOMContentLoaded', () => {
        initUI();
        connectSocket();
        bindCanvasListeners();
        requestAnimationFrame(updateCursorsLoop);
    });
})();
