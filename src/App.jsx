import { useEffect, useRef, useState } from 'react'

const languages = {
  English: { code: 'en-IN', name: 'English' }, Hindi: { code: 'hi-IN', name: 'Hindi' }, Bengali: { code: 'bn-IN', name: 'Bengali' },
  Tamil: { code: 'ta-IN', name: 'Tamil' }, Telugu: { code: 'te-IN', name: 'Telugu' }, Marathi: { code: 'mr-IN', name: 'Marathi' },
  Punjabi: { code: 'pa-IN', name: 'Punjabi' }, Gujarati: { code: 'gu-IN', name: 'Gujarati' }, Kannada: { code: 'kn-IN', name: 'Kannada' },
  Malayalam: { code: 'ml-IN', name: 'Malayalam' }, Odia: { code: 'or-IN', name: 'Odia' }, Assamese: { code: 'as-IN', name: 'Assamese' }
}
const crops = ['Rice', 'Wheat', 'Maize', 'Cotton', 'Sugarcane', 'Tomato', 'Potato', 'Onion', 'Pulses', 'Other']
const schemes = [
  { icon: '₹', name: 'PM-KISAN', group: 'Income support', text: 'Eligible landholding farmer families can receive income support in instalments. Check your beneficiary status and e-KYC through the official portal.', url: 'https://pmkisan.gov.in/' },
  { icon: '☂', name: 'PM Fasal Bima Yojana', group: 'Crop insurance', text: 'Crop insurance for notified crops and areas can help protect against specified natural risks. Enrolment windows and premiums depend on your state and season.', url: 'https://pmfby.gov.in/' },
  { icon: '⌂', name: 'Kisan Credit Card', group: 'Farm credit', text: 'A Kisan Credit Card can provide eligible farmers with timely credit for crop expenses and allied activities. Ask your bank or cooperative about eligibility.', url: 'https://www.myscheme.gov.in/schemes/kcc' },
  { icon: '▤', name: 'Soil Health Card', group: 'Soil & inputs', text: 'Soil testing and a Soil Health Card can guide nutrient use for your field. Contact your local agriculture department or soil testing laboratory.', url: 'https://soilhealth.dac.gov.in/' },
  { icon: '⌁', name: 'e-NAM', group: 'Market access', text: 'The electronic National Agriculture Market connects participating mandis and can help farmers discover prices and trading opportunities.', url: 'https://www.enam.gov.in/' },
  { icon: '✦', name: 'PMKSY – Per Drop More Crop', group: 'Irrigation', text: 'Micro-irrigation support may be available through state implementation of Per Drop More Crop. Subsidy, eligibility and application details vary by state.', url: 'https://pmksy.gov.in/' }
]
const initialChat = [{ role: 'saathi', text: 'Namaste! Ask me about your crops or how to use KhetSaathi.' }]

function requestFarmLocation() {
  return new Promise(resolve => {
    if (!navigator.geolocation) return resolve(null)
    navigator.geolocation.getCurrentPosition(
      position => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude, accuracy: position.coords.accuracy }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }
    )
  })
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem('khetsaathi-token') || '')
  const [page, setPage] = useState('dashboard'), [user, setUser] = useState(null), [cropsOwned, setCropsOwned] = useState([]), [language, setLanguage] = useState('English')
  const [weather, setWeather] = useState(null), [weatherLoading, setWeatherLoading] = useState(false), [weatherError, setWeatherError] = useState('')
  const [file, setFile] = useState(null), [preview, setPreview] = useState(''), [analysis, setAnalysis] = useState(null), [history, setHistory] = useState([])
  const [busy, setBusy] = useState(false), [chatOpen, setChatOpen] = useState(false), [messages, setMessages] = useState(initialChat), [question, setQuestion] = useState(''), [toast, setToast] = useState('')
  const [recording, setRecording] = useState(false), [transcribing, setTranscribing] = useState(false), [voiceHint, setVoiceHint] = useState('')
  const fileRef = useRef(null), chatRef = useRef(null), recorderRef = useRef(null), audioChunksRef = useRef([]), streamRef = useRef(null), recordingTimerRef = useRef(null)
  const notify = text => { setToast(text); setTimeout(() => setToast(''), 2800) }
  const api = async (url, options = {}) => {
    const response = await fetch(url, { ...options, headers: { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) } })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || 'Something went wrong. Please try again.')
    return data
  }
  const loadWeather = async () => {
    if (!user?.weather_location_saved) { setWeather(null); return }
    setWeatherLoading(true); setWeatherError('')
    try { const data = await api(`/api/weather?language=${encodeURIComponent(language)}`); setWeather(data) }
    catch (e) { setWeatherError(e.message) }
    finally { setWeatherLoading(false) }
  }
  const enableWeatherLocation = async () => {
    const location = await requestFarmLocation()
    if (!location) { setWeatherError('Location was not shared. Allow location access in your browser and try again.'); return }
    setWeatherLoading(true); setWeatherError('')
    try {
      const result = await api('/api/profile', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(location) })
      setUser(result.user)
    } catch (e) { setWeatherError(e.message) }
    finally { setWeatherLoading(false) }
  }
  const refresh = async () => {
    if (!token) return
    try { const data = await api('/api/me'); setUser(data.user); setCropsOwned(data.user.crops || []); setLanguage(data.user.language || 'English'); setHistory(data.scans || []); setPage(data.user.onboarding_complete ? 'dashboard' : 'onboarding') }
    catch { localStorage.removeItem('khetsaathi-token'); setToken(''); setUser(null) }
  }
  useEffect(() => { refresh() }, [token])
  useEffect(() => {
    if (page !== 'dashboard') return
    if (!user?.weather_location_saved) { setWeather(null); return }
    loadWeather()
    const refreshTimer = setInterval(loadWeather, 30 * 60 * 1000)
    return () => clearInterval(refreshTimer)
  }, [page, user?.id, user?.weather_location_saved, language, cropsOwned.join('|')])
  useEffect(() => () => { clearTimeout(recordingTimerRef.current); if (recorderRef.current?.state === 'recording') recorderRef.current.stop(); streamRef.current?.getTracks().forEach(track => track.stop()) }, [])
  const speak = (text, targetLanguage = language) => { if ('speechSynthesis' in window) { speechSynthesis.cancel(); const utterance = new SpeechSynthesisUtterance(text); const locale = languages[targetLanguage]?.code || languages.English.code; utterance.lang = locale; const voice = speechSynthesis.getVoices().find(v => v.lang.toLowerCase() === locale.toLowerCase()) || speechSynthesis.getVoices().find(v => v.lang.toLowerCase().startsWith(locale.slice(0, 2).toLowerCase())); if (voice) utterance.voice = voice; utterance.rate = .9; speechSynthesis.speak(utterance) } }
  const saveLanguage = async next => { setLanguage(next); if (token) api('/api/profile', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ language: next }) }).catch(() => {}) }
  const signOut = () => { localStorage.removeItem('khetsaathi-token'); setToken(''); setUser(null); setHistory([]); setPage('dashboard') }
  const choose = chosen => { if (!chosen?.type?.startsWith('image/')) return notify('Please choose a crop photo.'); if (chosen.size > 8e6) return notify('Please choose an image under 8 MB.'); setFile(chosen); setPreview(URL.createObjectURL(chosen)); setAnalysis(null) }
  const analyse = async () => {
    if (!file) return
    setBusy(true)
    try { const form = new FormData(); form.append('image', file); form.append('language', language); form.append('crop', cropsOwned.join(', ')); const data = await api('/api/analyze', { method: 'POST', body: form }); setAnalysis(data); setPage('result'); const fresh = await api('/api/scans'); setHistory(fresh.scans) }
    catch (e) { notify(e.message) } finally { setBusy(false) }
  }
  const showScan = () => { setFile(null); setPreview(''); setAnalysis(null); setPage('scan') }
  const openScan = async item => { setAnalysis(item.result); setPage('result') }
  const ask = async value => {
    const text = value.trim(); if (!text) return
    setMessages(current => [...current, { role: 'user', text }, { role: 'saathi', text: 'One moment…', pending: true }]); setQuestion('')
    try { const data = await api('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: text, language, crops: cropsOwned, app_context: true }) }); setMessages(current => [...current.filter(x => !x.pending), { role: 'saathi', text: data.answer }]); speak(data.answer) }
    catch (e) { setMessages(current => [...current.filter(x => !x.pending), { role: 'saathi', text: e.message }]) }
  }
  const listen = async () => {
    if (recording) { recorderRef.current?.stop(); return }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { setVoiceHint('This browser cannot record audio here. Please type your question.'); return }
    setVoiceHint('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true }); streamRef.current = stream
      const preferred = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported?.(type))
      const recorder = new MediaRecorder(stream, preferred ? { mimeType: preferred } : undefined)
      audioChunksRef.current = []; recorderRef.current = recorder
      recorder.ondataavailable = event => { if (event.data?.size) audioChunksRef.current.push(event.data) }
      recorder.onstop = async () => {
        clearTimeout(recordingTimerRef.current); streamRef.current?.getTracks().forEach(track => track.stop()); streamRef.current = null; setRecording(false)
        const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || 'audio/webm' }); audioChunksRef.current = []
        if (!blob.size) { setVoiceHint('No audio was captured. Try again or type your question.'); return }
        const extension = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('mp4') ? 'mp4' : blob.type.includes('wav') ? 'wav' : 'webm'
        const form = new FormData(); form.append('audio', blob, `voice-question.${extension}`); form.append('language', language); form.append('crops', cropsOwned.join(', '))
        setTranscribing(true); setVoiceHint('Transcribing…')
        try { const result = await api('/api/transcribe', { method: 'POST', body: form }); setQuestion(result.transcript); setVoiceHint(`Transcript in ${language}. Review it, edit anything that sounds wrong, then tap send.`) }
        catch (error) { setVoiceHint(error.message) }
        finally { setTranscribing(false) }
      }
      recorder.start(250); setRecording(true); setVoiceHint(`Recording in ${language}. Tap the microphone again when you’ve finished speaking.`)
      recordingTimerRef.current = setTimeout(() => { if (recorder.state === 'recording') recorder.stop() }, 30000)
    } catch (error) {
      streamRef.current?.getTracks().forEach(track => track.stop()); streamRef.current = null
      setVoiceHint(error.name === 'NotAllowedError' ? 'Microphone permission was denied. Allow microphone access in your browser, or type your question.' : 'Microphone could not start. Please try again or type your question.')
    }
  }
  if (!token) return <Login onLogin={async (sessionToken, location) => { if (location) { try { const response = await fetch('/api/profile', { method: 'PATCH', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sessionToken}` }, body: JSON.stringify(location) }); if (!response.ok) console.warn('Could not save the optional farm location.') } catch { console.warn('Could not save the optional farm location.') } } localStorage.setItem('khetsaathi-token', sessionToken); setToken(sessionToken) }} language={language} setLanguage={saveLanguage} />
  if (!user) return <div className="loading-screen">✦ &nbsp; Opening your farm…</div>
  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#" onClick={e => { e.preventDefault(); setPage('dashboard') }}><span className="brand-mark">✦</span>Khet<span>Saathi</span></a><div className="farm-label">YOUR FARM</div><nav className="side-nav">
      <button className={page === 'dashboard' ? 'active' : ''} onClick={() => setPage('dashboard')}><span>⌂</span> Dashboard</button>
      <button className={page === 'scan' ? 'active' : ''} onClick={showScan}><span>⌁</span> Daily crop check</button>
      <button className={page === 'shops' ? 'active' : ''} onClick={() => setPage('shops')}><span>⌖</span> Nearby farm shops</button>
      <button className={page === 'schemes' ? 'active' : ''} onClick={() => setPage('schemes')}><span>▤</span> Farmer schemes</button>
    </nav><div className="sidebar-bottom"><div className="profile-chip"><span className="profile-avatar">{user.name?.[0]?.toUpperCase() || 'F'}</span><div><b>{user.name}</b><small>{user.village || 'Farmer account'}</small></div></div><button className="signout" onClick={signOut}>↗ &nbsp; Sign out</button></div></aside>
    <div className="main-column"><header className="topbar"><div><span className="breadcrumb">{page === 'result' ? 'Daily crop check / Results' : page === 'schemes' ? 'Support for your farm' : page === 'shops' ? 'Find farm-input shops near you' : page === 'scan' ? 'Daily crop check' : 'Your farm at a glance'}</span></div><label className="language-picker">🌐 <select value={language} onChange={e => saveLanguage(e.target.value)}>{Object.keys(languages).map(x => <option key={x}>{x}</option>)}</select></label></header>
      <main className="page-content">{page === 'onboarding' ? <Onboarding user={user} onSave={async list => { try { await api('/api/profile', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ crops: list }) }); setCropsOwned(list); setPage('dashboard') } catch (e) { notify(e.message) } }} /> : page === 'dashboard' ? <Dashboard user={user} crops={cropsOwned} history={history} setPage={setPage} onScan={showScan} onOpenScan={openScan} weather={weather} weatherLoading={weatherLoading} weatherError={weatherError} onRefreshWeather={loadWeather} onEnableWeatherLocation={enableWeatherLocation} /> : page === 'scan' ? <Scan crops={cropsOwned} fileRef={fileRef} file={file} preview={preview} choose={choose} setFile={setFile} setPreview={setPreview} analyse={analyse} busy={busy} language={language} onDashboard={() => setPage('dashboard')} /> : page === 'result' ? <Result analysis={analysis || history[0]?.result} onScan={showScan} speak={speak} /> : page === 'shops' ? <ShopFinder api={api} /> : <Schemes language={language} />}</main>
    </div>
    <button className="assistant-fab" onClick={() => setChatOpen(x => !x)} aria-label="Open Saathi assistant">{chatOpen ? '×' : '✦'} <span>{chatOpen ? 'Close' : 'Ask Saathi'}</span></button>
    {chatOpen && <section className="assistant-panel"><div className="assistant-panel-head"><div className="saathi-face">✦</div><div><b>Saathi</b><small>Crop and app help · {language}</small></div><button onClick={() => setChatOpen(false)}>×</button></div><div className="messages" ref={chatRef}>{messages.map((m,i) => <div key={i} className={`bubble ${m.role === 'user' ? 'user' : 'saathi'}`}>{m.text}</div>)}</div><div className="chat-tools"><div className="voice-control"><button className={`mic ${recording ? 'recording' : ''}`} onClick={listen} disabled={transcribing} title={recording ? 'Stop recording' : 'Record a voice question'} aria-label={recording ? 'Stop recording' : 'Record a voice question'}>{recording ? '■' : transcribing ? '…' : '◉'}</button><small>{recording ? 'Stop' : transcribing ? 'Wait' : 'Voice'}</small></div><form className="chat-input" onSubmit={e => { e.preventDefault(); ask(question); setVoiceHint('') }}><input value={question} onChange={e => { setQuestion(e.target.value); if (voiceHint) setVoiceHint('') }} placeholder="Ask about crops or the app…" /><button className="send" disabled={!question.trim() || recording || transcribing}>↑</button></form></div>{voiceHint && <p className="voice-hint">{voiceHint}</p>}<p className="voice-language-note">Set the language menu to match the language you’re speaking. Your recording is transcribed by Groq and isn’t saved to your farm account; check or edit the words before sending.</p></section>}
    <div className={`toast ${toast ? 'show' : ''}`}>{toast}</div>
  </div>
}

function Login({ onLogin, language, setLanguage }) {
  const [mode, setMode] = useState('login'), [name, setName] = useState(''), [village, setVillage] = useState(''), [email, setEmail] = useState(''), [password, setPassword] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const submit = async e => { e.preventDefault(); setBusy(true); setError(''); try { const locationPromise = requestFarmLocation(); const response = await fetch(`/api/${mode}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, village, email, password, language }) }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Could not sign in.'); const location = await locationPromise; await onLogin(data.token, location) } catch (e) { setError(e.message) } finally { setBusy(false) } }
  return <main className="auth-page"><section className="auth-story"><a className="brand" href="#"><span className="brand-mark">✦</span>Khet<span>Saathi</span></a><div className="auth-copy"><div className="eyebrow">YOUR DIGITAL FIELD COMPANION</div><h1>Better days<br />begin <em>in the field.</em></h1><p>Keep a watchful eye on your crops, understand what they need, and find support for your farm.</p><div className="auth-illustration">🌾<div>✦ &nbsp; A little guidance, right when it matters.</div></div></div><small className="auth-foot">Made for growers, across Bharat</small></section><section className="auth-form-side"><div className="auth-form-wrap"><div className="language-picker">🌐 <select value={language} onChange={e => setLanguage(e.target.value)}>{Object.keys(languages).map(x => <option key={x}>{x}</option>)}</select></div><div className="auth-kicker">WELCOME TO KHETSAATHI</div><h2>{mode === 'login' ? 'Welcome back' : 'Create your account'}</h2><p className="muted">{mode === 'login' ? 'Sign in to check in on your farm.' : 'Start building a healthier season, one check-in at a time.'}</p><form onSubmit={submit} className="auth-form">{mode === 'signup' && <><label>Your name<input required value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Meera Devi" /></label><label>Village or district <span className="optional">Optional</span><input value={village} onChange={e => setVillage(e.target.value)} placeholder="Where is your farm?" /></label></>}<label>Email address<input type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" /></label><label>Password<input type="password" minLength="8" required value={password} onChange={e => setPassword(e.target.value)} placeholder="At least 8 characters" /></label>{error && <div className="form-error">{error}</div>}<button className="button primary auth-submit" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'} <span>→</span></button></form><p className="auth-switch">{mode === 'login' ? 'New to KhetSaathi?' : 'Already have an account?'} <button onClick={() => { setMode(mode === 'login' ? 'signup' : 'login'); setError('') }}>{mode === 'login' ? 'Create an account' : 'Sign in'}</button></p><div className="auth-note">With your permission, your farm location is saved for local weather updates. If you decline, you can still use KhetSaathi and enable it later.</div></div></section></main>
}

function Onboarding({ user, onSave }) { const [selected, setSelected] = useState([]), [other, setOther] = useState(''); const toggle = crop => setSelected(s => s.includes(crop) ? s.filter(x => x !== crop) : [...s, crop]); return <section className="onboarding-card"><div className="eyebrow">LET'S GET TO KNOW YOUR FARM</div><h1>What do you grow, {user.name?.split(' ')[0]}?</h1><p className="muted">Choose all the crops you grow. This helps Saathi tailor check-ins and crop advice to your fields.</p><div className="crop-options">{crops.map(c => <button className={selected.includes(c) ? 'picked' : ''} onClick={() => toggle(c)} key={c}>{selected.includes(c) ? '✓ ' : '+ '}{c}</button>)}</div>{selected.includes('Other') && <input className="other-crop" value={other} onChange={e => setOther(e.target.value)} placeholder="Tell us what else you grow" />}<button className="button primary" disabled={!selected.length} onClick={() => onSave(selected.map(c => c === 'Other' && other ? other : c))}>Save my crops <span>→</span></button><button className="skip-button" onClick={() => onSave([])}>I'll do this later</button></section> }

function Dashboard({ user, crops, history, setPage, onScan, onOpenScan, weather, weatherLoading, weatherError, onRefreshWeather, onEnableWeatherLocation }) { const recent = history.slice(0,3); const labels = weather?.labels || {}; return <><section className="welcome-row"><div><div className="eyebrow">YOUR FARM · {user.village || 'BHARAT'}</div><h1>Namaste, {user.name?.split(' ')[0]} <span>🌿</span></h1><p className="muted">A quick check-in today can help you catch changes early.</p></div><button className="button primary" onClick={onScan}>＋ &nbsp; Check my crops</button></section>{user.weather_location_saved ? <section className="weather-card"><div className="weather-heading"><div><div className="eyebrow">{labels.local_weather || 'LOCAL WEATHER'} · {weather?.location || user.village || 'YOUR FARM'}</div><h2>{weatherLoading && !weather ? 'Loading your local weather…' : weather?.condition || 'Weather update'}</h2><p>{weather?.observed_at ? `${labels.updated || 'Updated'} ${new Date(weather.observed_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}` : (labels.based_on_location || 'Based on your saved device location')}</p></div><div className="weather-temperature">{weather?.temperature_c != null ? `${Math.round(weather.temperature_c)}°` : '—'}<small>{labels.feels_like || 'Feels like'} {weather?.feels_like_c != null ? `${Math.round(weather.feels_like_c)}°` : '—'}</small></div><button className="button outline weather-refresh" onClick={onRefreshWeather} disabled={weatherLoading}>{weatherLoading ? 'Updating…' : '↻ Refresh'}</button></div>{weather && <><div className="weather-facts"><div><small>{labels.today || 'TODAY'}</small><b>{weather.today_low_c != null ? `${Math.round(weather.today_low_c)}°` : '—'} / {weather.today_high_c != null ? `${Math.round(weather.today_high_c)}°` : '—'}</b><span>{labels.low_high || 'Low / high'}</span></div><div><small>{labels.rain_chance || 'RAIN CHANCE'}</small><b>{weather.rain_probability_percent != null ? `${weather.rain_probability_percent}%` : '—'}</b><span>Today</span></div><div><small>{labels.humidity || 'HUMIDITY'}</small><b>{weather.humidity_percent != null ? `${weather.humidity_percent}%` : '—'}</b><span>{labels.current || 'Current'}</span></div><div><small>{labels.wind || 'WIND'}</small><b>{weather.wind_kmh != null ? `${Math.round(weather.wind_kmh)} km/h` : '—'}</b><span>{labels.current || 'Current'}</span></div></div><div className="weather-advice"><b>{labels.field_guidance || 'Field guidance'} for {crops.length ? crops.join(', ') : 'your farm'}</b><ul>{weather.advice?.map((tip, i) => <li key={i}>{tip}</li>)}</ul></div><div className="weather-source">{labels.forecast_from || 'Forecast from'} <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a>{labels.model_notice ? ` · ${labels.model_notice}` : ' · Model-based local forecast; conditions can vary between nearby fields'}{weather.location_accuracy_m ? ` · ${labels.device_accuracy || 'Device location accuracy about'} ${Math.round(weather.location_accuracy_m)} m` : ''}</div></>}{weatherError && <p className="weather-error">{weatherError}</p>}</section> : <section className="weather-empty"><div className="weather-empty-icon">⌖</div><div><b>Get weather for your farm</b><p>Share your device location to see current conditions, rain chance, and practical field guidance on the dashboard.</p>{weatherError && <p className="weather-error">{weatherError}</p>}<button className="button primary" onClick={onEnableWeatherLocation} disabled={weatherLoading}>{weatherLoading ? 'Getting location…' : 'Enable local weather'}</button></div></section>}<section className="dashboard-stats"><div><span className="stat-icon">🌱</span><small>YOUR CROPS</small><strong>{crops.length || '—'}</strong><span>{crops.length ? crops.join(' · ') : 'Add crops to personalise your farm'}</span></div><div><span className="stat-icon">⌁</span><small>FIELD CHECKS</small><strong>{history.length}</strong><span>{history.length ? 'Saved to your crop history' : 'Your first check-in is waiting'}</span></div><div><span className="stat-icon">◷</span><small>LAST CHECK-IN</small><strong>{recent[0] ? new Date(recent[0].created_at).toLocaleDateString('en-IN', { day:'numeric', month:'short' }) : 'Today'}</strong><span>{recent[0]?.result?.plant || 'Ready when you are'}</span></div></section><section className="dashboard-section"><div className="section-title"><div><div className="eyebrow">A SIMPLE DAILY ROUTINE</div><h2>Care starts with a closer look.</h2></div><button className="text-link" onClick={() => setPage('schemes')}>Explore farmer schemes →</button></div><div className="checkin-card"><div className="checkin-art">🌿</div><div><span className="tag">DAILY CROP CHECK-IN</span><h3>How are your crops doing today?</h3><p>Take a clear photo of a plant or affected leaf. Saathi will look for visible signs and suggest practical next steps.</p><button className="button primary" onClick={onScan}>Start a crop check <span>→</span></button></div></div></section><section className="dashboard-section history-section"><div className="section-title"><div><div className="eyebrow">YOUR FIELD NOTES</div><h2>Recent check-ins</h2></div>{history.length > 3 && <span className="muted">Latest 3</span>}</div>{recent.length ? <div className="history-list">{recent.map(item => <button className="history-row" key={item.id} onClick={() => onOpenScan(item)}><span className="history-thumb">🌱</span><span className="history-main"><b>{item.result?.plant || item.crop || 'Crop check'}</b><small>{item.result?.status || 'Analysis saved'} · {item.crop || 'Field check'}</small></span><span className="history-date">{new Date(item.created_at).toLocaleDateString('en-IN', { day:'numeric', month:'short' })}</span><span>→</span></button>)}</div> : <div className="empty-history">Your crop check results will appear here so you can keep track of changes over time.</div>}</section></> }

function Scan({ crops, fileRef, file, preview, choose, setFile, setPreview, analyse, busy, language, onDashboard }) { return <section className="scan-page"><button className="back-link" onClick={onDashboard}>← &nbsp; Dashboard</button><div className="eyebrow">DAILY CROP CHECK-IN</div><h1>Take a closer look.</h1><p className="muted">Upload a clear photo of a plant or affected leaves. Your results will be saved to your crop history.</p><div className="scan-layout"><div className="dropzone" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); choose(e.dataTransfer.files[0]) }} onClick={() => fileRef.current.click()}><input ref={fileRef} type="file" accept="image/*" capture="environment" hidden onChange={e => choose(e.target.files[0])} />{preview ? <><img className="crop-preview" src={preview} alt="Crop preview" /><button className="remove-image" onClick={e => { e.stopPropagation(); setFile(null); setPreview('') }}>×</button></> : <div className="upload-empty"><div className="camera-icon">⌁</div><strong>Take a photo or upload one</strong><span>JPG, PNG or WEBP · max 8 MB</span><span className="button outline">Choose photo</span></div>}</div><div className="scan-instructions"><div className="tag">BEFORE YOU SCAN</div><h3>A clear photo helps Saathi see more.</h3><ul><li>Use natural daylight</li><li>Focus on affected leaves</li><li>Include the whole plant if you can</li></ul><div className="crop-context"><small>YOUR CROPS</small><b>{crops.length ? crops.join(' · ') : 'Not selected yet'}</b></div><button className="button primary scan-button" onClick={analyse} disabled={!file || busy}>{busy ? 'Checking crop details…' : <>Analyse my crop <span>→</span></>}</button><p className="privacy">🔒 Photo is used only for this analysis.</p></div></div><p className="result-language">Your assessment and care guidance will be prepared in {language}.</p></section> }

function Result({ analysis: data, onScan, speak }) {
  if (!data) return <section className="empty-result"><div className="stat-icon">⌁</div><h1>No check-in to show yet</h1><p className="muted">Scan a crop to get an AI generated assessment and care suggestions.</p><button className="button primary" onClick={onScan}>Start a crop check <span>→</span></button></section>
  const list = items => items?.map((item, i) => <li key={i}>{item}</li>)
  const reportText = [data.plant, data.summary, data.status, ...(data.observations || []), ...(data.possible_causes || []), data.cause_note, data.care, ...(data.actions || []), ...(data.monitoring || []), ...(data.avoid || []), data.disclaimer].filter(Boolean).join('. ')
  return <section className="result-page">
    <div className="result-actions"><button className="back-link" onClick={onScan}>← &nbsp; New check-in</button><button className="text-link" onClick={() => speak(reportText, data.language)}>▶ &nbsp; Listen to full report</button></div>
    <div className="result-hero"><div><div className="eyebrow">AI CROP HEALTH ASSESSMENT · {Math.round((data.confidence || 0) * 100)}% VISUAL CONFIDENCE</div><h1>{data.plant}</h1><div className="result-status">● &nbsp; {data.status} <span>· {data.category}</span></div><p className="report-summary">{data.summary || 'This assessment is based on visible signs in the uploaded photo.'}</p><div className="severity-line"><span className={`severity-pill severity-${(data.severity || 'moderate').toLowerCase()}`}>{data.severity || 'Severity not rated'}</span><span>Photo-based screening · not a confirmed diagnosis</span></div></div><div className="health-score"><strong>{data.health_score ?? '—'}</strong><span>/100<br />visual score</span></div></div>
    <p className="score-note">The health score is a rough visual indicator from this photo. It is not a lab result, yield estimate, or probability of disease.</p>
    {data.demo && <div className="demo-banner">AI service unavailable. This is sample guidance and not an analysis of your uploaded photo.</div>}
    <div className="report-section-heading"><div className="eyebrow">UNDERSTANDING THIS CHECK-IN</div><h2>What the photo may be telling us</h2></div>
    <div className="result-cards"><article className="result-card"><div className="result-card-icon">◉</div><div className="eyebrow">VISIBLE FINDINGS</div><p className="card-intro">These are visual observations, separated from possible explanations.</p><ul>{list(data.observations)}</ul></article><article className="result-card causes-card"><div className="result-card-icon">⌕</div><div className="eyebrow">POSSIBLE CAUSES · NOT A DIAGNOSIS</div><ul>{list(data.possible_causes)}</ul><p>{data.cause_note}</p></article></div>
    <article className="result-card care-card detailed-care"><div className="result-card-icon">✦</div><div className="eyebrow">CROP-SPECIFIC CARE</div><p>{data.care}</p><div className="eyebrow steps-heading">PRIORITISED NEXT STEPS</div><ol>{list(data.actions)}</ol></article>
    <div className="result-cards followup-cards"><article className="result-card"><div className="result-card-icon">◷</div><div className="eyebrow">WHAT TO MONITOR</div><ul>{list(data.monitoring)}</ul></article><article className="result-card avoid-card"><div className="result-card-icon">!</div><div className="eyebrow">WHAT TO AVOID FOR NOW</div><ul>{list(data.avoid)}</ul></article></div>
    <div className="report-limits"><b>When to seek local help</b><p>{data.disclaimer || 'This photo-based AI screening cannot confirm a disease. If symptoms spread, plants wilt rapidly, or the cause remains unclear, show the crop to your local Krishi Vigyan Kendra or agriculture officer.'}</p></div>
    <div className="result-bottom"><span>✓ Saved to your crop history</span><button className="button primary" onClick={onScan}>Check another crop <span>→</span></button></div>
  </section>
}

function ShopFinder({ api }) {
  const [busy, setBusy] = useState(false), [shops, setShops] = useState(null), [error, setError] = useState(''), [searched, setSearched] = useState(false)
  const search = () => {
    if (!navigator.geolocation) { setError('Location access is not available in this browser. You can still use your map app to search for farm supply shops.'); return }
    setBusy(true); setError(''); setShops(null); setSearched(false)
    navigator.geolocation.getCurrentPosition(async position => {
      try { const { latitude, longitude } = position.coords; const result = await api(`/api/nearby-shops?lat=${encodeURIComponent(latitude)}&lon=${encodeURIComponent(longitude)}`); setShops(result.shops || []); setSearched(true) }
      catch (e) { setError(e.message) } finally { setBusy(false) }
    }, geoError => {
      const message = geoError.code === 1 ? 'Location permission was not granted. Allow location access in your browser settings and try again.' : geoError.code === 2 ? 'Your device could not determine its location. Try again outdoors or check device location settings.' : 'Location lookup timed out. Please try again.'
      setError(message); setBusy(false)
    }, { enableHighAccuracy: false, timeout: 15000, maximumAge: 300000 })
  }
  return <section className="shops-page"><div className="eyebrow">LOCAL FARM SUPPORT</div><h1>Find farm-input shops nearby.</h1><p className="muted shops-intro">With your permission, KhetSaathi can use your current location to look for mapped agricultural-input suppliers within 12 km. Your coordinates are used for this search and aren’t saved to your account.</p>
    <div className="location-consent-card"><div className="location-icon">⌖</div><div><b>Search from where you are</b><p>Your browser will ask before sharing your location. We use OpenStreetMap listings for agricultural inputs such as seeds, fertiliser, and crop-protection supplies.</p><button className="button primary" onClick={search} disabled={busy}>{busy ? 'Finding nearby shops…' : 'Use my location'} <span>→</span></button></div></div>
    {error && <div className="location-error">{error}</div>}
    {busy && <div className="shops-loading">Searching nearby map listings…</div>}
    {searched && shops?.length === 0 && <div className="shops-empty"><b>No mapped farm-input shops found nearby.</b><p>OpenStreetMap coverage varies by area. Try again from a nearby town or search your map app for “agricultural supplies”.</p></div>}
    {!!shops?.length && <div className="nearby-results"><div className="nearby-heading"><div><div className="eyebrow">WITHIN 12 KM</div><h2>{shops.length} {shops.length === 1 ? 'shop' : 'shops'} found</h2></div><button className="text-link" onClick={search}>↻ &nbsp; Search again</button></div><div className="shop-list">{shops.map(shop => <article className="nearby-shop" key={shop.id}><div className="shop-pin">⌖</div><div className="shop-copy"><div className="shop-title-row"><h3>{shop.name}</h3><span className="shop-distance">{shop.distance_km} km</span></div><span className="tag">{shop.type}</span>{shop.products && <p className="shop-products">May list: {shop.products.replaceAll(';', ', ')}</p>}{shop.address && <p className="shop-address">{shop.address}</p>}{shop.opening_hours && <p className="shop-meta">Hours listed: {shop.opening_hours}</p>}{shop.phone && <p className="shop-meta"><a href={`tel:${shop.phone}`}>{shop.phone}</a></p>}<a className="directions-link" href={`https://www.google.com/maps/dir/?api=1&destination=${shop.lat},${shop.lon}`} target="_blank" rel="noreferrer">Get directions ↗</a></div></article>)}</div><p className="osm-attribution">Shop listings © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a></p></div>}
    <div className="shops-caution"><b>Please confirm before travelling.</b> Map listings may be missing or out of date; call the shop to check it is open and carries what you need. A listing is not a product recommendation or endorsement. For pesticide choice and safe use, consult your local agriculture officer or KVK.</div>
  </section>
}

function Schemes({ language }) { const [items, setItems] = useState(schemes), [translated, setTranslated] = useState(language === 'English'); useEffect(() => { let alive = true; fetch('/api/translate-schemes', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ language, schemes }) }).then(r => r.json()).then(d => { if (alive) { setItems(d.schemes || schemes); setTranslated(language === 'English' || !!d.translated) } }).catch(() => { if (alive) { setItems(schemes); setTranslated(false) } }); return () => { alive = false } }, [language]); return <section className="schemes-page"><div className="eyebrow">SUPPORT FOR YOUR FARM</div><h1>Find a little more support.</h1><p className="muted schemes-intro">Explore national programmes that may help with farm income, insurance, credit and better access to markets. {language !== 'English' && !translated ? 'Scheme translations need the AI service to be configured.' : ''} Official links have the latest eligibility and application information.</p><div className="scheme-grid">{items.map(s => <article className="scheme-card" key={s.name}><div className="scheme-icon">{s.icon}</div><span className="tag">{s.group.toUpperCase()}</span><h2>{s.name}</h2><p>{s.text}</p><a href={s.url} target="_blank" rel="noreferrer">Visit official website ↗</a></article>)}</div><p className="schemes-note">Availability, eligibility, benefits and application dates can change or vary by state. Confirm details with the official programme portal or your local agriculture office.</p></section> }
