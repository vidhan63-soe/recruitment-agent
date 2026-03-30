"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

// ── Types ──────────────────────────────────────────────────────

type Phase = "loading" | "setup" | "interview" | "report" | "already_completed";

type TranscriptMsg = { role: "ai" | "candidate"; text: string };

type QAItem = {
  question: string;
  answer: string;
  words: number;
  // Populated by backend LLM scoring at submit time
  score?: number;
  feedback?: string;
  key_points_hit?: string[];
  key_points_missed?: string[];
};

type Alert = { text: string; level: "warning" | "danger" | "info"; time: string };

type SessionData = {
  candidate_name: string;
  email: string;
  role: string;
  questions: string[] | null;
  num_questions: number;
  difficulty: string;
};

const FALLBACK_QUESTIONS = [
  "Tell me about yourself and why you're interested in this role.",
  "Describe a challenging project you worked on and how you navigated it.",
  "What are your strongest skills relevant to this position?",
  "Walk me through a situation where you had to meet a tight deadline.",
  "Tell me about a time you worked in a team and had to resolve a disagreement.",
  "How do you stay updated with developments in your field?",
  "What is your approach to solving complex problems?",
  "Where do you see yourself in 3–5 years, and how does this role fit your goals?",
];

const BACKEND = process.env.NEXT_PUBLIC_API_URL || "";

// ── Main component (wrapped in Suspense for useSearchParams) ──

function InterviewApp() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  const [phase, setPhase] = useState<Phase>("loading");
  const [sessionData, setSessionData] = useState<SessionData | null>(null);
  const [persona, setPersona] = useState<"rahul" | "alex">("rahul");
  const [notes, setNotes] = useState("");
  const [transcript, setTranscript] = useState<TranscriptMsg[]>([]);
  const [questionIdx, setQuestionIdx] = useState(-1);
  const [totalQuestions, setTotalQuestions] = useState(0);
  const [currentQuestion, setCurrentQuestion] = useState("Preparing your interview...");
  const [questionPhase, setQuestionPhase] = useState("INTRO");
  const [isAISpeaking, setIsAISpeaking] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [micStatus, setMicStatus] = useState("Ready");
  const [gaugeOverall, setGaugeOverall] = useState(50);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [tabWarning, setTabWarning] = useState(false);
  const [elapsedSecs, setElapsedSecs] = useState(0);
  const [report, setReport] = useState<any>(null);
  const [submitting, setSubmitting] = useState(false);

  // Refs for async interview loop
  const abortedRef = useRef(false);
  const hasEndedRef = useRef(false);
  const recognitionRef = useRef<any>(null);
  const ttsVoiceRef = useRef<SpeechSynthesisVoice | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const confidenceTrendRef = useRef<number[]>([]);
  const qaRef = useRef<QAItem[]>([]);
  const startTimeRef = useRef<number>(0);
  const interviewPhaseRef = useRef<Phase>("loading");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  // Sarvam TTS audio (ref so we can cancel mid-play)
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);

  // Video / face-detection refs
  const videoRef = useRef<HTMLVideoElement>(null);
  const videoStreamRef = useRef<MediaStream | null>(null);
  const videoRecorderRef = useRef<MediaRecorder | null>(null);
  const videoChunksRef = useRef<Blob[]>([]);
  const faceDetectorRef = useRef<any>(null);
  const faceCheckIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const noFaceCountRef = useRef(0);
  const isAISpeakingRef = useRef(false); // ref-copy to avoid stale closure in face loop

  const [cameraActive, setCameraActive] = useState(false);
  const [faceStatus, setFaceStatus] = useState<"ok" | "missing" | "multiple" | "unavailable">("unavailable");

  // Sync phase to ref (for event listeners)
  useEffect(() => { interviewPhaseRef.current = phase; }, [phase]);
  // Sync isAISpeaking to ref (used in face detection interval closure)
  useEffect(() => { isAISpeakingRef.current = isAISpeaking; }, [isAISpeaking]);

  // Attach camera stream to <video> element after it mounts (phase change causes re-render)
  useEffect(() => {
    if (cameraActive && videoRef.current && videoStreamRef.current) {
      videoRef.current.srcObject = videoStreamRef.current;
      videoRef.current.play().catch(() => {});
    }
  }, [cameraActive]);

  // Load token / session data
  useEffect(() => {
    if (!token) { setPhase("setup"); return; }
    fetch(`${BACKEND}/api/interview-session/${token}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) { setPhase("setup"); return; }

        // ── One-time link guard ──
        if (data.status === "completed") {
          setSessionData({
            candidate_name: data.candidate_name || "Candidate",
            email: "",
            role: data.question_config?.role || "Software Engineer",
            questions: null,
            num_questions: 0,
            difficulty: "adaptive",
          });
          setPhase("already_completed");
          return;
        }

        const cfg = data.question_config || {};
        setSessionData({
          candidate_name: data.candidate_name || cfg.candidate_name || "Candidate",
          email: cfg.email || "",
          role: cfg.role || "Software Engineer",
          questions: Array.isArray(cfg.questions) && cfg.questions.length > 0
            ? cfg.questions.map((q: any) => (typeof q === "string" ? q : q.question || ""))
            : null,
          num_questions: cfg.num_questions || 8,
          difficulty: cfg.difficulty || "adaptive",
        });
        setPhase("setup");
      })
      .catch(() => setPhase("setup"));
  }, [token]);

  // Voice loading — prefer explicitly male voices for the "Alex" interviewer persona
  useEffect(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    const load = () => {
      const voices = window.speechSynthesis.getVoices();
      const en = voices.filter((v) => v.lang.startsWith("en"));
      const nm = (v: SpeechSynthesisVoice) => v.name.toLowerCase();

      // Priority: any voice with "male" in the name, then known male names, then non-female non-local
      ttsVoiceRef.current =
        // Explicitly labeled male (e.g. "Google UK English Male")
        en.find((v) => nm(v).includes("male")) ||
        // Microsoft / Windows built-in male voices
        en.find((v) => nm(v).includes("david")) ||
        en.find((v) => nm(v).includes("mark") && !nm(v).includes("remark")) ||
        en.find((v) => nm(v).includes("james")) ||
        en.find((v) => nm(v).includes("guy")) ||
        en.find((v) => nm(v).includes("daniel") && !nm(v).includes("female")) ||
        en.find((v) => nm(v).includes("fred")) ||
        en.find((v) => nm(v).includes("alex") && !nm(v).includes("female")) ||
        // Avoid any explicitly female voice
        en.find((v) => !nm(v).includes("female") && !nm(v).includes("zira") && !nm(v).includes("cortana") && !v.localService) ||
        en.find((v) => !nm(v).includes("female") && !nm(v).includes("zira")) ||
        en[0] || (voices.length ? voices[0] : null);
    };
    window.speechSynthesis.onvoiceschanged = load;
    load();
  }, []);

  // Tab-switch detection: show alert to candidate, still report to backend
  useEffect(() => {
    const handleVisibility = () => {
      if (document.hidden && interviewPhaseRef.current === "interview") {
        setTabWarning(true);
        setTimeout(() => setTabWarning(false), 6000);
        addAlert("Tab switch detected", "warning");
        captureSnapshot("tab_switch");
        fetch(`${BACKEND}/api/cheating/report`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: "tab_switch", details: {} }),
        }).catch(() => {});
      }
    };
    const handleBlur = () => {
      if (interviewPhaseRef.current === "interview") {
        fetch(`${BACKEND}/api/cheating/report`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: "focus_loss", details: {} }),
        }).catch(() => {});
      }
    };
    const handleCopy = () => {
      if (interviewPhaseRef.current === "interview") {
        addAlert("Copy action detected", "danger");
        fetch(`${BACKEND}/api/cheating/report`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type: "copy_paste", details: { action: "copy" } }) }).catch(() => {});
      }
    };
    const handlePaste = () => {
      if (interviewPhaseRef.current === "interview") {
        addAlert("Paste action detected", "danger");
        fetch(`${BACKEND}/api/cheating/report`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type: "copy_paste", details: { action: "paste" } }) }).catch(() => {});
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("blur", handleBlur);
    document.addEventListener("copy", handleCopy);
    document.addEventListener("paste", handlePaste);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("blur", handleBlur);
      document.removeEventListener("copy", handleCopy);
      document.removeEventListener("paste", handlePaste);
    };
  }, []);

  // DevTools detection
  useEffect(() => {
    let devOpen = false;
    const id = setInterval(() => {
      if (interviewPhaseRef.current !== "interview") return;
      const open = window.outerWidth - window.innerWidth > 160 || window.outerHeight - window.innerHeight > 160;
      if (open && !devOpen) {
        devOpen = true;
        addAlert("DevTools opened", "danger");
        fetch(`${BACKEND}/api/cheating/report`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type: "devtools", details: {} }) }).catch(() => {});
      } else if (!open) devOpen = false;
    }, 1000);
    return () => clearInterval(id);
  }, []);

  // Timer
  useEffect(() => {
    if (phase === "interview") {
      startTimeRef.current = Date.now();
      timerRef.current = setInterval(() => setElapsedSecs(Math.floor((Date.now() - startTimeRef.current) / 1000)), 1000);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [phase]);

  // Auto-scroll transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  // ── Helpers ──────────────────────────────────────────────────

  function addAlert(text: string, level: "warning" | "danger" | "info") {
    const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    setAlerts((prev) => [...prev, { text, level, time }]);
  }

  /** Strip any <think>...</think> reasoning blocks that might leak from the LLM. */
  function cleanAIText(text: string): string {
    return text.replace(/<think>[\s\S]*?<\/think>/gi, "").replace(/<think>[\s\S]*/gi, "").trim();
  }

  function addMessage(role: "ai" | "candidate", text: string) {
    const clean = role === "ai" ? cleanAIText(text) : text;
    setTranscript((prev) => [...prev, { role, text: clean }]);
  }

  async function speak(text: string): Promise<void> {
    text = cleanAIText(text);
    if (!text) return;

    // Cancel any in-progress audio (Sarvam or browser)
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }

    // ── Try backend TTS (Sarvam neural voice) ──
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 7000);
      const res = await fetch(`${BACKEND}/api/interview/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text.slice(0, 600), persona }),
        signal: controller.signal,
      });
      clearTimeout(timeout);
      if (res.ok) {
        const data = await res.json();
        if (data.audio_base64) {
          const mime = data.format === "mp3" ? "audio/mpeg" : "audio/wav";
          await new Promise<void>((resolve) => {
            const audio = new Audio(`data:${mime};base64,${data.audio_base64}`);
            currentAudioRef.current = audio;
            const safety = setTimeout(() => { currentAudioRef.current = null; resolve(); }, text.length * 110 + 6000);
            audio.onended = () => { clearTimeout(safety); currentAudioRef.current = null; resolve(); };
            audio.onerror = () => { clearTimeout(safety); currentAudioRef.current = null; resolve(); };
            audio.play().catch(() => { clearTimeout(safety); currentAudioRef.current = null; resolve(); });
          });
          return; // ← Edge TTS succeeded
        }
      }
    } catch {
      // Network error / timeout — fall through to Web Speech API
    }

    // ── Web Speech API fallback ──
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    return new Promise<void>((resolve) => {
      const utt = new SpeechSynthesisUtterance(text);
      if (ttsVoiceRef.current) utt.voice = ttsVoiceRef.current;
      utt.lang = "en-US";
      utt.rate = 0.9;
      utt.pitch = 0.85;   // lower pitch = more masculine
      utt.volume = 1.0;
      const safety = setTimeout(resolve, text.length * 90 + 4000);
      utt.onend = () => { clearTimeout(safety); resolve(); };
      utt.onerror = () => { clearTimeout(safety); resolve(); };
      window.speechSynthesis.speak(utt);
    });
  }

  // ── Answer quality helpers ────────────────────────────────────

  /** Returns true if the answer is empty, a marker string, or fewer than 4 real words. */
  function detectEmpty(answer: string): boolean {
    const markers = ["[no response detected]", "[listening error]", "[could not start microphone]"];
    const trimmed = answer.trim().toLowerCase();
    if (!trimmed || markers.includes(trimmed)) return true;
    const words = trimmed.split(/\s+/).filter((w) => w.length > 1);
    return words.length < 4;
  }

  /** Returns true if the candidate expresses confusion, uncertainty, or inability to answer. */
  function detectConfusion(answer: string): boolean {
    const text = answer.toLowerCase();
    const confusionPhrases = [
      "i don't know", "i dont know", "i do not know",
      "not sure", "i'm not sure", "i am not sure",
      "no idea", "i have no idea", "haven't done", "have not done",
      "never done", "never done this", "never done that",
      "can't answer", "cannot answer", "don't have experience",
      "i have no experience", "i'm not familiar", "i am not familiar",
      "don't remember", "can't think", "cannot think",
      "i'm blank", "i am blank", "drawing a blank",
      "pass", "skip this", "next question",
    ];
    return confusionPhrases.some((phrase) => text.includes(phrase));
  }

  /** Pick an encouraging response when candidate expresses confusion, varied by attempt. */
  function buildEncouragement(question: string, attempt: number): string {
    const prompts = [
      `No worries at all — that's a completely normal feeling. Take a deep breath. Even if you're unsure, think about a time in your experience that relates to this topic, and talk through what you did. There are no wrong answers here.`,
      `I appreciate your honesty. Let's approach this differently — you don't need to have a perfect answer. Just share what comes to mind, even if it's a partial thought or a related example from your work. Go ahead, take your time.`,
      `That's okay! Sometimes we know more than we think we do. Just start talking — even a rough idea or a related story works. What's the first thing that comes to mind when you hear this question?`,
    ];
    return prompts[Math.min(attempt, prompts.length - 1)];
  }

  /** Silence prompt when candidate says nothing. */
  function buildSilencePrompt(attempt: number): string {
    const prompts = [
      `I didn't quite catch that. Could you please take a moment and share your thoughts out loud?`,
      `Still with you — please go ahead whenever you're ready. Speak clearly and I'll pick it up.`,
    ];
    return prompts[Math.min(attempt, prompts.length - 1)];
  }

  /** Capture a JPEG frame from the live camera and upload it to the backend. */
  function captureSnapshot(reason: string = "periodic"): void {
    const video = videoRef.current;
    if (!video || !cameraActive || !token) return;
    try {
      const canvas = document.createElement("canvas");
      canvas.width  = Math.min(video.videoWidth  || 640, 640);
      canvas.height = Math.min(video.videoHeight || 480, 480);
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      // Un-mirror: draw the raw (un-flipped) camera feed
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        if (!blob) return;
        fetch(`${BACKEND}/api/interview-session/${token}/snapshot?reason=${encodeURIComponent(reason)}`, {
          method: "POST",
          headers: { "Content-Type": "image/jpeg" },
          body: blob,
        }).catch(() => {});
      }, "image/jpeg", 0.8);
    } catch {}
  }

  /** Start periodic face-detection using the browser's FaceDetector API (Chrome built-in). */
  function startFaceDetection() {
    if (typeof window === "undefined" || !("FaceDetector" in window)) {
      setFaceStatus("unavailable");
      return; // Browser doesn't support it — just record video silently
    }
    try {
      faceDetectorRef.current = new (window as any).FaceDetector({ fastMode: true, maxDetectedFaces: 4 });
    } catch {
      setFaceStatus("unavailable");
      return;
    }

    let periodicTick = 0; // used to capture a snapshot every ~30 s (10 ticks × 3 s)

    faceCheckIntervalRef.current = setInterval(async () => {
      const video = videoRef.current;
      if (!video || interviewPhaseRef.current !== "interview") return;

      // Periodic snapshot every 30 s regardless of face status
      periodicTick++;
      if (periodicTick % 10 === 0) captureSnapshot("periodic");

      if (isAISpeakingRef.current) return; // don't interrupt while AI is speaking

      try {
        const faces: any[] = await faceDetectorRef.current.detect(video);

        if (faces.length === 0) {
          noFaceCountRef.current++;
          setFaceStatus("missing");

          // Alert + snapshot after 2 consecutive misses (~6 s)
          if (noFaceCountRef.current >= 2) {
            addAlert("Face not visible in camera", "warning");
            captureSnapshot("face_missing");
            fetch(`${BACKEND}/api/cheating/report`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ type: "face_not_detected", details: { consecutive: noFaceCountRef.current } }),
            }).catch(() => {});
          }
          // Speak reminder every 3rd consecutive miss
          if (noFaceCountRef.current % 3 === 0) {
            speak("Please ensure your face is clearly visible to the camera.");
          }

        } else if (faces.length > 1) {
          noFaceCountRef.current = 0;
          setFaceStatus("multiple");
          addAlert(`Multiple faces detected (${faces.length})`, "danger");
          captureSnapshot(`multiple_faces_${faces.length}`);
          fetch(`${BACKEND}/api/cheating/report`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type: "multiple_faces", details: { count: faces.length } }),
          }).catch(() => {});

        } else {
          noFaceCountRef.current = 0;
          setFaceStatus("ok");
        }
      } catch {
        // Detection error — ignore this tick
      }
    }, 3000); // check every 3 seconds
  }

  function listen(timeoutMs = 45000): Promise<string> {
    return new Promise((resolve) => {
      const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (!SR) {
        // Show text fallback inline — resolve when user submits
        setMicStatus("Type your answer below (speech not supported):");
        // We'll use a special state for this
        (window as any).__textFallbackResolve = resolve;
        setIsListening(true);
        return;
      }
      const rec = new SR();
      rec.continuous = true;
      rec.interimResults = true;
      rec.lang = "en-US";
      rec.maxAlternatives = 1;
      recognitionRef.current = rec;
      let finalText = "";
      let silenceTimer: ReturnType<typeof setTimeout> | null = null;

      function resetSilence() {
        if (silenceTimer) clearTimeout(silenceTimer);
        // 5 s of silence after last detected speech before stopping
        silenceTimer = setTimeout(() => rec.stop(), 5000);
      }

      rec.onresult = (e: any) => {
        let interim = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          if (e.results[i].isFinal) finalText += e.results[i][0].transcript + " ";
          else interim = e.results[i][0].transcript;
        }
        setMicStatus(interim || "● Listening…");
        resetSilence();
      };
      rec.onend = () => {
        if (silenceTimer) clearTimeout(silenceTimer);
        recognitionRef.current = null;
        setIsListening(false);
        setMicStatus("Processing…");
        resolve(finalText.trim() || "[No response detected]");
      };
      rec.onerror = (e: any) => {
        if (silenceTimer) clearTimeout(silenceTimer);
        recognitionRef.current = null;
        setIsListening(false);
        resolve(finalText.trim() || "[Listening error]");
      };
      try {
        rec.start();
        setIsListening(true);
        setMicStatus("● Listening…");
        resetSilence();
        setTimeout(() => { try { rec.stop(); } catch {} }, timeoutMs);
      } catch {
        resolve("[Could not start microphone]");
      }
    });
  }

  async function callAIRespond(question: string, answer: string, idx: number, total: number, name: string, role: string): Promise<string> {
    try {
      const res = await fetch(`${BACKEND}/api/interview/ai-respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, answer, question_idx: idx, total_questions: total, candidate_name: name, role }),
      });
      if (res.ok) { const d = await res.json(); return d.response || ""; }
    } catch {}
    const fallbacks = [
      "Thank you for sharing that.",
      "That's really helpful, I appreciate it.",
      "Good, that gives me a clear picture.",
      "Thanks — I like how you approached that.",
      "Noted, thank you. Let's keep going.",
      "Great perspective, thank you.",
      "Interesting — I appreciate you walking me through that.",
    ];
    return fallbacks[idx % fallbacks.length];
  }

  // ── Interview flow ────────────────────────────────────────────

  async function checkinAndStart() {
    if (token) {
      try {
        await fetch(`${BACKEND}/api/interview/checkin`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token, notes }),
        });
      } catch {}
    }
    await startInterview();
  }

  async function startInterview() {
    const sd = sessionData;
    const name = sd?.candidate_name || "Candidate";
    const role = sd?.role || "Software Engineer";
    const numQ = sd?.num_questions || 8;
    const questions = (sd?.questions && sd.questions.length > 0) ? sd.questions : FALLBACK_QUESTIONS.slice(0, numQ);

    setTotalQuestions(questions.length);
    setPhase("interview");
    abortedRef.current = false;
    hasEndedRef.current = false;
    qaRef.current = [];
    confidenceTrendRef.current = [];
    audioChunksRef.current = [];
    videoChunksRef.current = [];
    noFaceCountRef.current = 0;

    // Notify backend
    try {
      await fetch(`${BACKEND}/api/interview/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_name: name, role, num_questions: questions.length, difficulty: sd?.difficulty || "adaptive" }),
      });
    } catch {}

    // ── Start camera (for snapshots + face detection) + audio recording ──
    let cameraStarted = false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
      });
      videoStreamRef.current = stream;
      setCameraActive(true); // triggers useEffect → attaches stream to <video> element

      // Audio-only recorder (for playback in recruiter panel)
      const audioStream = new MediaStream(stream.getAudioTracks());
      const aMime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
      const audioRecorder = new MediaRecorder(audioStream, { mimeType: aMime });
      audioRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
      audioRecorder.start(1000);
      mediaRecorderRef.current = audioRecorder;

      cameraStarted = true;
      // Small delay so the <video> element mounts and face detection has a frame to read
      setTimeout(() => startFaceDetection(), 1500);
    } catch {
      // Camera unavailable — fall back to audio only
    }

    if (!cameraStarted) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const aMime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
        const audioRecorder = new MediaRecorder(stream, { mimeType: aMime });
        audioRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
        audioRecorder.start(1000);
        mediaRecorderRef.current = audioRecorder;
      } catch {
        // No audio either — continue silently
      }
    }

    // Run interview loop
    await runInterview(questions, name, role);
  }

  async function runInterview(questions: string[], name: string, role: string) {
    const MAX_RETRIES = 3; // max attempts per question (silence + confusion combined)

    // ── Greeting ──
    setQuestionPhase("GREETING");
    setCurrentQuestion("AI Interviewer is greeting you…");
    setIsAISpeaking(true);
    const interviewerName = persona === "rahul" ? "Rahul" : "Alex";
    const greeting = persona === "rahul"
      ? `Namaste ${name}! I'm Rahul, your AI interviewer for the ${role} position today. ` +
        `I'll be asking you ${questions.length} questions — please take your time and answer naturally, there's no rush. ` +
        `Just speak clearly and be yourself. Shall we begin?`
      : `Hello ${name}! I'm Alex, your AI interviewer for the ${role} role today. ` +
        `We have ${questions.length} questions lined up — just speak naturally and take as much time as you need. ` +
        `There are no trick questions, so just be yourself. Alright, let's get started!`;
    addMessage("ai", greeting);
    await speak(greeting);
    setIsAISpeaking(false);

    if (abortedRef.current) { endInterview(); return; }

    // ── Question loop ──
    for (let i = 0; i < questions.length; i++) {
      if (abortedRef.current) break;

      setQuestionIdx(i);
      setQuestionPhase(`QUESTION ${i + 1} / ${questions.length}`);
      setCurrentQuestion(questions[i]);

      // Natural question intro (vary phrasing so it doesn't sound robotic)
      const intros = [
        `Alright, here's question ${i + 1}.`,
        `Great. Moving on to question ${i + 1}.`,
        `Thanks for that. Now,`,
        `Perfect. Next question:`,
        `Good. Question ${i + 1}:`,
      ];
      const questionPrefix = i === 0 ? "Let's start with:" : intros[i % intros.length];
      const fullQuestion = `${questionPrefix} ${questions[i]}`;

      setIsAISpeaking(true);
      setMicStatus("🔊 AI speaking…");
      addMessage("ai", questions[i]);
      await speak(fullQuestion);
      setIsAISpeaking(false);

      if (abortedRef.current) break;

      // ── Listen loop with retry for silence / confusion ──
      let answer = "";
      let attempts = 0;
      let confusionCount = 0;

      while (attempts < MAX_RETRIES) {
        setIsListening(true);
        setMicStatus("● Listening…");
        const raw = await listen(45000);
        setIsListening(false);

        if (abortedRef.current) break;

        // ── Case 1: Empty / silence ──
        if (detectEmpty(raw)) {
          attempts++;
          if (attempts >= MAX_RETRIES) {
            answer = raw; // accept after max retries
            break;
          }
          const silenceMsg = buildSilencePrompt(attempts - 1);
          setIsAISpeaking(true);
          addMessage("ai", silenceMsg);
          await speak(silenceMsg);
          setIsAISpeaking(false);
          if (abortedRef.current) break;
          continue;
        }

        // ── Case 2: Candidate expresses confusion / "I don't know" ──
        if (detectConfusion(raw) && confusionCount < 2) {
          confusionCount++;
          attempts++;
          if (attempts >= MAX_RETRIES) {
            answer = raw; // they tried — accept it
            break;
          }
          const encouragement = buildEncouragement(questions[i], confusionCount - 1);
          setIsAISpeaking(true);
          addMessage("ai", encouragement);
          await speak(encouragement);
          setIsAISpeaking(false);
          if (abortedRef.current) break;
          continue;
        }

        // ── Good answer — accept ──
        answer = raw;
        break;
      }

      if (abortedRef.current) break;

      addMessage("candidate", answer);

      // Gauge update (live visual only — word count heuristic, not scoring)
      const words = answer.split(/\s+/).filter((w) => w.length > 0).length;
      qaRef.current.push({ question: questions[i], answer, words });
      const gaugeScore = Math.min(10, Math.max(1, Math.round(words / 15)));
      confidenceTrendRef.current.push(gaugeScore);
      const avg = confidenceTrendRef.current.reduce((a, b) => a + b, 0) / confidenceTrendRef.current.length;
      setGaugeOverall(Math.round((avg / 10) * 100));

      // AI transition response
      setIsAISpeaking(true);
      setMicStatus("Processing…");
      const aiResp = await callAIRespond(questions[i], answer, i, questions.length, name, role);
      if (!abortedRef.current && aiResp) {
        addMessage("ai", aiResp);
        await speak(aiResp);
      }
      setIsAISpeaking(false);
    }

    if (abortedRef.current) { endInterview(); return; }

    // ── Closing ──
    setQuestionIdx(questions.length);
    setQuestionPhase("CLOSING");
    setCurrentQuestion("Interview complete");
    setIsAISpeaking(true);
    const closing =
      `And that brings us to the end of your interview, ${name}. ` +
      `Thank you so much for your time today — I really appreciate you sharing your thoughts and experiences. ` +
      `Our team will carefully review your responses and be in touch with you soon. ` +
      `Best of luck, and I hope to see you again!`;
    addMessage("ai", closing);
    await speak(closing);
    setIsAISpeaking(false);

    setTimeout(() => endInterview(), 1500);
  }

  async function endInterview() {
    if (hasEndedRef.current) return;
    hasEndedRef.current = true;
    abortedRef.current = true;
    if (timerRef.current) clearInterval(timerRef.current);
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    if (recognitionRef.current) { try { recognitionRef.current.stop(); } catch {} }

    // Stop face detection
    if (faceCheckIntervalRef.current) clearInterval(faceCheckIntervalRef.current);

    // Stop audio recording
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      await new Promise<void>((resolve) => {
        recorder.onstop = () => resolve();
        recorder.stop();
      });
    }

    // Stop camera stream tracks
    if (videoStreamRef.current) {
      videoStreamRef.current.getTracks().forEach((t) => t.stop());
      setCameraActive(false);
    }

    // Build report
    const qa = qaRef.current;
    const avgWords = qa.length > 0 ? qa.reduce((s, x) => s + x.words, 0) / qa.length : 0;
    const overallScore = parseFloat(Math.min(10, Math.max(1, (avgWords / 50) * 10)).toFixed(1));
    const integrityAlerts = alerts.length;
    const rec =
      overallScore >= 7 ? "Strong Hire" :
      overallScore >= 5.5 ? "Hire" :
      overallScore >= 4 ? "Maybe — Needs Further Evaluation" : "No Hire";

    const reportObj = {
      candidate_name: sessionData?.candidate_name || "Candidate",
      role: sessionData?.role || "",
      overall_score: overallScore,
      recommendation: rec,
      duration_minutes: startTimeRef.current ? Math.round((Date.now() - startTimeRef.current) / 60000) : 0,
      transcript: qa,
      integrity_alerts: integrityAlerts,
      integrity_details: alerts.map((a) => `${a.text} (${a.time})`),
      confidence_trend: confidenceTrendRef.current,
    };

    setReport(reportObj);
    setPhase("report");

    // Submit report + audio + video to backend
    if (token) {
      setSubmitting(true);
      try {
        await fetch(`${BACKEND}/api/interview-session/${token}/submit-report`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ report: reportObj }),
        });
      } catch {}

      // Upload audio
      if (audioChunksRef.current.length > 0) {
        try {
          const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
          await fetch(`${BACKEND}/api/interview-session/${token}/audio`, {
            method: "POST", headers: { "Content-Type": "audio/webm" }, body: blob,
          });
        } catch {}
      }

      setSubmitting(false);
    }
  }

  function skipCurrentAnswer() {
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch {}
    }
  }

  // Text fallback submit
  function submitTextAnswer() {
    const input = document.getElementById("textFallbackInput") as HTMLTextAreaElement | null;
    const text = input?.value.trim() || "[No answer given]";
    const resolve = (window as any).__textFallbackResolve;
    if (resolve) { resolve(text); (window as any).__textFallbackResolve = null; }
    setIsListening(false);
    setMicStatus("Processing…");
  }

  // ── Timer display ─────────────────────────────
  const mins = String(Math.floor(elapsedSecs / 60)).padStart(2, "0");
  const secs = String(elapsedSecs % 60).padStart(2, "0");

  // ══════════════════════════════════════════════
  // RENDER
  // ══════════════════════════════════════════════

  if (phase === "loading") {
    return (
      <div style={S.page}>
        <div style={{ color: "#8888a0", textAlign: "center", marginTop: "40vh" }}>Loading interview…</div>
      </div>
    );
  }

  if (phase === "already_completed") {
    return (
      <div style={S.page}>
        <Header timer="00:00" statusDot="idle" statusText="Interview Closed" />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "80vh", gap: 24, padding: "40px 24px" }}>
          <div style={{ fontSize: 64 }}>🔒</div>
          <div style={{ textAlign: "center" }}>
            <h2 style={{ fontSize: 28, fontWeight: 700, color: "#e8e8f0", marginBottom: 8 }}>Interview Already Submitted</h2>
            <p style={{ fontSize: 15, color: "#8888a0", maxWidth: 440, lineHeight: 1.6 }}>
              You have already completed this interview.
              Each link can only be used once to maintain the integrity of your submission.
            </p>
            <p style={{ fontSize: 14, color: "#555570", maxWidth: 440, lineHeight: 1.6, marginTop: 12 }}>
              If you believe this is an error or need to retake, please contact the recruiter — they can reset your interview link.
            </p>
          </div>
          <div style={{ padding: "16px 32px", borderRadius: 12, background: "#12131a", border: "1px solid #2a2b3a", textAlign: "center" }}>
            <p style={{ fontSize: 13, color: "#8888a0" }}>
              Candidate: <strong style={{ color: "#e8e8f0" }}>{sessionData?.candidate_name}</strong>
              {sessionData?.role ? <> &nbsp;·&nbsp; Role: <strong style={{ color: "#e8e8f0" }}>{sessionData.role}</strong></> : null}
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (phase === "setup") {
    const sd = sessionData;
    return (
      <div style={S.page}>
        <Header timer="00:00" statusDot="idle" statusText="Ready" />
        <div style={S.setupWrap}>
          <div style={S.setupCard}>
            {sd ? (
              <>
                <h2 style={S.setupTitle}>Welcome to Your Interview</h2>
                <p style={S.setupSub}>Review your details below and add any notes, then begin.</p>

                <div style={S.profileStack}>
                  <ProfileRow icon="👤" label="Candidate Name" value={sd.candidate_name} />
                  <ProfileRow icon="✉️" label="Email" value={sd.email || "—"} />
                  <ProfileRow icon="💼" label="Position" value={sd.role || "—"} />
                </div>

                {/* Voice / Persona selector */}
                <div style={{ marginBottom: 24 }}>
                  <label style={S.formLabel}>Choose Your Interviewer</label>
                  <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
                    {(["rahul", "alex"] as const).map((p) => {
                      const isRahul = p === "rahul";
                      const selected = persona === p;
                      return (
                        <button
                          key={p}
                          onClick={() => setPersona(p)}
                          style={{
                            flex: 1, padding: "14px 12px", borderRadius: 12, cursor: "pointer",
                            border: `2px solid ${selected ? "var(--accent)" : "var(--border)"}`,
                            background: selected ? "rgba(99,102,241,0.12)" : "var(--bg)",
                            color: "var(--text)", textAlign: "left", transition: "all 0.15s",
                          }}
                        >
                          <div style={{ fontSize: 22, marginBottom: 4 }}>{isRahul ? "🇮🇳" : "🇺🇸"}</div>
                          <div style={{ fontWeight: 700, fontSize: 15 }}>{isRahul ? "Rahul" : "Alex"}</div>
                          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
                            {isRahul ? "Indian-English · Sarvam AI" : "American-English · Edge TTS"}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div style={{ marginBottom: 20 }}>
                  <label style={S.formLabel}>Notes / Corrections (optional)</label>
                  <textarea
                    style={S.textarea}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Preferred name, accessibility needs, corrections, or anything else for the interviewer…"
                  />
                </div>

                <button style={S.btnStart} onClick={checkinAndStart}>🎙 Begin Interview</button>

                {/* LinkedIn / Demo disclaimer */}
                <div style={{
                  marginTop: 24, padding: "12px 16px", borderRadius: 10,
                  background: "rgba(99,102,241,0.07)", border: "1px solid rgba(99,102,241,0.2)",
                  fontSize: 12, color: "var(--muted)", lineHeight: 1.6,
                }}>
                  <span style={{ color: "var(--accent)", fontWeight: 600 }}>🚀 RecruitAI Demo</span>
                  {" — "}AI-powered recruitment platform with automated screening, ranking, and voice interviews.<br />
                  <span style={{ opacity: 0.8 }}>
                    Built with FastAPI · Next.js · ChromaDB · Sarvam AI · Edge TTS.
                    {" "}Want this for your org? <strong style={{ color: "var(--text)" }}>DM the developer</strong> or{" "}
                    <strong style={{ color: "var(--text)" }}>set it up locally</strong> — full source on GitHub.
                  </span>
                </div>
              </>
            ) : (
              <>
                <h2 style={S.setupTitle}>Configure Interview</h2>
                <p style={S.setupSub}>No session token — running in direct mode.</p>
                <button style={S.btnStart} onClick={() => {
                  setSessionData({ candidate_name: "Candidate", email: "", role: "Software Engineer", questions: null, num_questions: 8, difficulty: "adaptive" });
                  checkinAndStart();
                }}>🎙 Start Interview</button>
              </>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (phase === "interview") {
    const faceBorderColor =
      faceStatus === "ok" ? "#22c55e" :
      faceStatus === "missing" ? "#ef4444" :
      faceStatus === "multiple" ? "#f97316" : "#6366f1";
    const faceLabel =
      faceStatus === "ok" ? "✓ Face OK" :
      faceStatus === "missing" ? "⚠ No face" :
      faceStatus === "multiple" ? "⚠ Multiple" : "📷 Camera";

    return (
      <div style={S.page}>
        {/* Tab-switch warning banner */}
        {tabWarning && (
          <div style={S.tabWarning}>
            ⚠️ Please stay on this tab during your interview! Tab switching has been noted.
          </div>
        )}

        <Header timer={`${mins}:${secs}`} statusDot={isListening ? "recording" : "live"} statusText={isAISpeaking ? "AI speaking…" : isListening ? "Listening…" : "In progress"} />

        {/* ── Floating camera preview ── */}
        {cameraActive && (
          <div style={{ position: "fixed", bottom: 88, left: 20, zIndex: 200 }}>
            <div style={{
              position: "relative", width: 168, height: 126, borderRadius: 12, overflow: "hidden",
              border: `2px solid ${faceBorderColor}`,
              boxShadow: `0 4px 24px rgba(0,0,0,0.5), 0 0 0 1px rgba(0,0,0,0.3)`,
              transition: "border-color 0.5s",
            }}>
              <video
                ref={videoRef}
                autoPlay
                muted
                playsInline
                style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scaleX(-1)" }}
              />
              {/* Status badge */}
              <div style={{
                position: "absolute", bottom: 5, right: 5,
                fontSize: 10, fontWeight: 600,
                background: "rgba(0,0,0,0.72)", color: faceBorderColor,
                borderRadius: 4, padding: "2px 6px", letterSpacing: "0.3px",
              }}>
                {faceLabel}
              </div>
              {/* Recording dot */}
              <div style={{
                position: "absolute", top: 5, left: 5,
                width: 8, height: 8, borderRadius: "50%",
                background: "#ef4444",
                boxShadow: "0 0 6px rgba(239,68,68,0.8)",
                animation: "recPulse 1.2s ease-in-out infinite",
              }} />
            </div>
          </div>
        )}

        <div style={S.interviewLayout}>
          {/* LEFT: main area */}
          <div style={S.interviewMain}>
            {/* Question bar */}
            <div style={S.questionBar}>
              <div style={S.questionPhase}>{questionPhase}</div>
              <div style={S.questionText}>{currentQuestion}</div>
              <div style={S.progressRow}>
                {Array.from({ length: totalQuestions }).map((_, i) => (
                  <div key={i} style={{
                    ...S.progressDot,
                    background: i < questionIdx ? "#22c55e" : i === questionIdx ? "#6366f1" : "#2a2b3a",
                    boxShadow: i === questionIdx ? "0 0 6px rgba(99,102,241,0.6)" : "none",
                  }} />
                ))}
              </div>
            </div>

            {/* Transcript */}
            <div style={S.transcriptArea}>
              {transcript.map((msg, i) => (
                <div key={i} style={S.transcriptMsg}>
                  <div style={{ ...S.msgAvatar, background: msg.role === "ai" ? "#6366f1" : "#2d5a3d" }}>
                    {msg.role === "ai" ? "🎯" : "👤"}
                  </div>
                  <div>
                    <div style={S.msgName}>{msg.role === "ai" ? "AI Interviewer" : "You"}</div>
                    <div style={S.msgText}>{msg.text}</div>
                  </div>
                </div>
              ))}
              {/* Text fallback input (shown when SpeechRecognition unavailable) */}
              {isListening && !(window as any).SpeechRecognition && !(window as any).webkitSpeechRecognition && (
                <div style={{ display: "flex", gap: 8, padding: "8px 0" }}>
                  <textarea id="textFallbackInput" rows={2} placeholder="Type your answer…"
                    style={{ flex: 1, padding: 8, background: "#1a1b25", border: "1px solid #2a2b3a", borderRadius: 6, color: "#e8e8f0", fontFamily: "inherit", fontSize: 13, resize: "none", outline: "none" }} />
                  <button onClick={submitTextAnswer}
                    style={{ padding: "8px 16px", background: "#6366f1", color: "white", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 13, alignSelf: "flex-end" }}>
                    Send
                  </button>
                </div>
              )}
              <div ref={transcriptEndRef} />
            </div>

            {/* Audio controls */}
            <div style={S.audioControls}>
              <button
                style={{ ...S.micBtn, background: isListening ? "#ef4444" : "transparent", borderColor: isListening ? "#ef4444" : "#6366f1", color: isListening ? "white" : "#6366f1" }}
                onClick={skipCurrentAnswer}
                title={isListening ? "Skip / stop answering" : "Mic controlled by AI"}>
                🎙️
              </button>
              <div style={S.audioViz}>
                {Array.from({ length: 40 }).map((_, i) => (
                  <div key={i} style={{ ...S.vizBar, height: `${isListening ? 4 + Math.random() * 24 : 4}px`, opacity: isListening ? 0.8 : 0.3 }} />
                ))}
              </div>
              <span style={{ fontSize: 12, color: "#8888a0" }}>{micStatus}</span>
            </div>
          </div>

          {/* RIGHT: sidebar */}
          <div style={S.sidebar}>
            {/* Live score */}
            <div style={S.sidebarSection}>
              <div style={S.sidebarTitle}>Live Confidence</div>
              <div style={S.gaugeRow}>
                <span style={{ fontSize: 13, color: "#e8e8f0" }}>Overall</span>
                <div style={S.gaugeBarWrap}>
                  <div style={{ ...S.gaugeBarFill, width: `${gaugeOverall}%`, background: gaugeOverall >= 60 ? "#22c55e" : gaugeOverall >= 35 ? "#eab308" : "#ef4444" }} />
                </div>
                <span style={{ fontSize: 13, fontFamily: "monospace", width: 35, textAlign: "right" }}>
                  {((gaugeOverall / 100) * 10).toFixed(1)}
                </span>
              </div>
            </div>

            {/* Integrity */}
            <div style={S.sidebarSection}>
              <div style={S.sidebarTitle}>Integrity Monitor</div>
              {alerts.length === 0 ? (
                <p style={{ fontSize: 13, color: "#8888a0", textAlign: "center", padding: "12px 0" }}>✓ No issues detected</p>
              ) : (
                alerts.slice(-5).map((a, i) => (
                  <div key={i} style={{ ...S.alertItem, background: a.level === "danger" ? "rgba(239,68,68,0.1)" : "rgba(234,179,8,0.1)", color: a.level === "danger" ? "#ef4444" : "#eab308", marginBottom: 6 }}>
                    {a.level === "danger" ? "⚠️" : "⚡"} {a.text}
                    <span style={{ marginLeft: "auto", opacity: 0.6, fontSize: 11 }}>{a.time}</span>
                  </div>
                ))
              )}
            </div>

            {/* Info */}
            <div style={S.sidebarSection}>
              <div style={S.sidebarTitle}>Session Info</div>
              <div style={{ fontSize: 13, color: "#8888a0", lineHeight: 1.8 }}>
                <div>Name: <span style={{ color: "#e8e8f0" }}>{sessionData?.candidate_name || "—"}</span></div>
                <div>Role: <span style={{ color: "#e8e8f0" }}>{sessionData?.role || "—"}</span></div>
                <div>Questions: <span style={{ color: "#e8e8f0" }}>{totalQuestions}</span></div>
              </div>
            </div>

            <button style={S.btnEnd} onClick={endInterview}>End Interview & Submit Report</button>
          </div>
        </div>
        <style>{`@keyframes recPulse { 0%,100% { opacity:1; transform:scale(1) } 50% { opacity:0.4; transform:scale(0.7) } }`}</style>
      </div>
    );
  }

  // ── SUBMITTED SCREEN (candidate sees only this — no scores) ──────────
  if (phase === "report") {
    const qa: QAItem[] = report?.transcript || [];
    return (
      <div style={S.page}>
        <Header timer={`${mins}:${secs}`} statusDot="idle" statusText="Interview Complete" />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "80vh", gap: 24, padding: "40px 24px" }}>
          {submitting ? (
            <>
              <div style={{ width: 56, height: 56, borderRadius: "50%", border: "3px solid #6366f1", borderTopColor: "transparent", animation: "spin 0.8s linear infinite" }} />
              <p style={{ fontSize: 16, color: "#8888a0" }}>Submitting your interview…</p>
            </>
          ) : (
            <>
              <div style={{ fontSize: 64 }}>✅</div>
              <div style={{ textAlign: "center" }}>
                <h2 style={{ fontSize: 28, fontWeight: 700, color: "#e8e8f0", marginBottom: 8 }}>Interview Submitted</h2>
                <p style={{ fontSize: 15, color: "#8888a0", maxWidth: 420, lineHeight: 1.6 }}>
                  Thank you for completing your interview. Your responses have been recorded and will be reviewed by the hiring team.
                </p>
              </div>
              <div style={{ padding: "16px 32px", borderRadius: 12, background: "#12131a", border: "1px solid #2a2b3a", textAlign: "center" }}>
                <p style={{ fontSize: 13, color: "#8888a0" }}>
                  <strong style={{ color: "#e8e8f0" }}>{qa.length}</strong> question{qa.length !== 1 ? "s" : ""} answered
                  {report?.duration_minutes ? ` · ${report.duration_minutes} min` : ""}
                </p>
              </div>
              <p style={{ fontSize: 13, color: "#555570", marginTop: 8 }}>You may now close this window.</p>
            </>
          )}
        </div>
        <style>{`
          @keyframes spin { to { transform: rotate(360deg) } }
          @keyframes recPulse { 0%,100% { opacity:1; transform:scale(1) } 50% { opacity:0.4; transform:scale(0.7) } }
        `}</style>
      </div>
    );
  }

  return null;
}

// ── Sub-components ─────────────────────────────────────────────

function Header({ timer, statusDot, statusText }: { timer: string; statusDot: "idle" | "live" | "recording"; statusText: string }) {
  const dotColor = statusDot === "live" ? "#22c55e" : statusDot === "recording" ? "#ef4444" : "#8888a0";
  return (
    <div style={S.header}>
      <div style={S.logo}>
        <div style={S.logoIcon}>🎯</div>
        AI Interviewer
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: dotColor, boxShadow: statusDot !== "idle" ? `0 0 8px ${dotColor}` : "none", transition: "all 0.3s" }} />
        <span style={{ fontSize: 13, color: "#8888a0" }}>{statusText}</span>
        <span style={{ fontFamily: "monospace", fontSize: 18, color: "#8888a0" }}>{timer}</span>
      </div>
    </div>
  );
}

function ProfileRow({ icon, label, value }: { icon: string; label: string; value: string }) {
  return (
    <div style={S.profileRow}>
      <span style={{ fontSize: 18, width: 28, textAlign: "center", flexShrink: 0 }}>{icon}</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: "#8888a0", marginBottom: 2 }}>{label}</div>
        <div style={{ fontSize: 15, fontWeight: 500, color: "#e8e8f0" }}>{value}</div>
      </div>
      <div style={{ fontSize: 10, background: "rgba(99,102,241,0.15)", color: "#6366f1", padding: "2px 8px", borderRadius: 4, fontWeight: 600 }}>Read-only</div>
    </div>
  );
}

// ── Styles (inline, avoids Tailwind dependency) ────────────────

const S: Record<string, React.CSSProperties> = {
  page: { fontFamily: "'DM Sans', system-ui, sans-serif", background: "#0a0b0f", color: "#e8e8f0", minHeight: "100vh", overflowX: "hidden" },
  header: { padding: "16px 32px", borderBottom: "1px solid #2a2b3a", display: "flex", justifyContent: "space-between", alignItems: "center", background: "#12131a" },
  logo: { fontSize: 20, fontWeight: 700, display: "flex", alignItems: "center", gap: 10 },
  logoIcon: { width: 32, height: 32, background: "#6366f1", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 },
  setupWrap: { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "calc(100vh - 60px)", padding: 40 },
  setupCard: { background: "#12131a", border: "1px solid #2a2b3a", borderRadius: 16, padding: 40, maxWidth: 600, width: "100%" },
  setupTitle: { fontSize: 28, fontWeight: 700, marginBottom: 8 },
  setupSub: { color: "#8888a0", marginBottom: 32 },
  profileStack: { display: "flex", flexDirection: "column", marginBottom: 24 },
  profileRow: { display: "flex", alignItems: "center", padding: "14px 16px", background: "#1a1b25", border: "1px solid #2a2b3a", gap: 14 },
  formLabel: { display: "block", fontSize: 13, fontWeight: 600, color: "#8888a0", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6 } as React.CSSProperties,
  textarea: { width: "100%", padding: "12px 16px", background: "#1a1b25", border: "1px solid #2a2b3a", borderRadius: 8, color: "#e8e8f0", fontSize: 15, fontFamily: "inherit", outline: "none", resize: "vertical", minHeight: 100, lineHeight: 1.6 } as React.CSSProperties,
  btnStart: { width: "100%", padding: 14, background: "#6366f1", color: "white", border: "none", borderRadius: 10, fontSize: 16, fontWeight: 600, cursor: "pointer", marginTop: 24 },
  tabWarning: { position: "fixed", top: 0, left: 0, right: 0, zIndex: 999, background: "#eab308", color: "#000", textAlign: "center", padding: "12px 16px", fontWeight: 600, fontSize: 14 } as React.CSSProperties,
  interviewLayout: { display: "grid", gridTemplateColumns: "1fr 340px", height: "calc(100vh - 60px)" },
  interviewMain: { display: "flex", flexDirection: "column", borderRight: "1px solid #2a2b3a" },
  questionBar: { padding: "20px 28px", background: "#12131a", borderBottom: "1px solid #2a2b3a" },
  questionPhase: { fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: 1, color: "#6366f1", marginBottom: 4 } as React.CSSProperties,
  questionText: { fontSize: 16, fontWeight: 500, lineHeight: 1.5 },
  progressRow: { marginTop: 12, display: "flex", gap: 4 },
  progressDot: { flex: 1, height: 3, borderRadius: 2, transition: "all 0.3s" },
  transcriptArea: { flex: 1, overflowY: "auto", padding: "20px 28px" } as React.CSSProperties,
  transcriptMsg: { marginBottom: 16, display: "flex", gap: 12 },
  msgAvatar: { width: 36, height: 36, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, flexShrink: 0 },
  msgName: { fontSize: 12, fontWeight: 600, color: "#8888a0", marginBottom: 4 },
  msgText: { fontSize: 14, lineHeight: 1.6 },
  audioControls: { padding: "16px 28px", borderTop: "1px solid #2a2b3a", background: "#12131a", display: "flex", alignItems: "center", gap: 16 },
  micBtn: { width: 48, height: 48, borderRadius: "50%", border: "2px solid #6366f1", background: "transparent", color: "#6366f1", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20 },
  audioViz: { flex: 1, height: 40, display: "flex", alignItems: "center", gap: 2 },
  vizBar: { width: 3, background: "#6366f1", borderRadius: 2, transition: "height 0.1s", opacity: 0.6 },
  sidebar: { background: "#12131a", overflowY: "auto", display: "flex", flexDirection: "column" } as React.CSSProperties,
  sidebarSection: { padding: "16px 20px", borderBottom: "1px solid #2a2b3a" },
  sidebarTitle: { fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1, color: "#8888a0", marginBottom: 12 } as React.CSSProperties,
  gaugeRow: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 },
  gaugeBarWrap: { width: 120, height: 6, background: "#1a1b25", borderRadius: 3, overflow: "hidden" },
  gaugeBarFill: { height: "100%", borderRadius: 3, transition: "width 0.5s ease" },
  alertItem: { padding: "8px 12px", borderRadius: 6, fontSize: 12, display: "flex", alignItems: "center", gap: 8 },
  btnEnd: { margin: "16px 20px", padding: 12, background: "#ef4444", color: "white", border: "none", borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: "pointer" },
  reportWrap: { maxWidth: 900, margin: "0 auto", padding: 40 },
  reportHeader: { textAlign: "center", marginBottom: 40 } as React.CSSProperties,
  reportGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 },
  reportCard: { background: "#12131a", border: "1px solid #2a2b3a", borderRadius: 12, padding: 20 },
  cardTitle: { fontSize: 14, fontWeight: 600, marginBottom: 12 },
};

// ── Page export with Suspense (required for useSearchParams) ──

export default function CandidateInterviewPage() {
  return (
    <Suspense fallback={<div style={{ background: "#0a0b0f", color: "#8888a0", minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>Loading…</div>}>
      <InterviewApp />
    </Suspense>
  );
}
