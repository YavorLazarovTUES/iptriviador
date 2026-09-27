import { useEffect, useState } from 'react'

const AVATARS = ['knight-1', 'knight-2', 'knight-3', 'knight-4']
const FORMS = {
  login: ['username', 'password'],
  register: ['username', 'email', 'nickname', 'password', 'password_confirm'],
}

async function api(path, method = 'GET', body) {
  const res = await fetch(`/api/auth/${path}/`, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': document.cookie.match(/csrftoken=([^;]+)/)?.[1] },
    body: body && JSON.stringify(body),
  })
  const data = res.status === 204 ? null : await res.json()
  if (!res.ok) throw data.errors
  return data
}

export default function App() {
  const [user, setUser] = useState() // undefined = loading, null = anonymous
  const [screen, setScreen] = useState('login')
  const [errors, setErrors] = useState({})
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api('csrf').then(() => api('me')).then(setUser, () => setUser(null))
  }, [])

  const submit = (path, method = 'POST') => async (e) => {
    e.preventDefault()
    try {
      setUser(await api(path, method, Object.fromEntries(new FormData(e.target))))
      setErrors({})
      setSaved(method === 'PATCH')
    } catch (err) {
      setErrors(err)
      setSaved(false)
    }
  }
  const switchScreen = () => { setScreen(screen === 'login' ? 'register' : 'login'); setErrors({}) }
  const logout = async () => { await api('logout', 'POST'); setUser(null) }
  const fieldErrors = (name) => [errors[name]].flat().filter(Boolean).map((m) => <small key={m}>{m}</small>)

  if (user === undefined) return null
  if (user) return (
    <form onSubmit={submit('me', 'PATCH')} onChange={() => setSaved(false)}>
      <h1>{user.profile.nickname}</h1>
      <p>{user.username} · {user.email}</p>
      <label>nickname<input name="nickname" defaultValue={user.profile.nickname} />{fieldErrors('nickname')}</label>
      <label>avatar
        <select name="avatar_key" defaultValue={user.profile.avatar_key}>
          {AVATARS.map((a) => <option key={a}>{a}</option>)}
        </select>
      </label>
      {fieldErrors('detail')}
      {saved && <p className="saved">Changes saved.</p>}
      <button>Save</button>
      <button type="button" onClick={logout}>Logout</button>
    </form>
  )
  return (
    <form key={screen} onSubmit={submit(screen)}>
      <h1>{screen === 'login' ? 'Login' : 'Register'}</h1>
      {FORMS[screen].map((name) => (
        <label key={name}>{name.replace('_', ' ')}
          <input name={name} type={name.startsWith('password') ? 'password' : name === 'email' ? 'email' : 'text'} required />
          {fieldErrors(name)}
        </label>
      ))}
      {fieldErrors('non_field_errors')}{fieldErrors('detail')}
      <button>{screen === 'login' ? 'Login' : 'Register'}</button>
      <button type="button" onClick={switchScreen}>{screen === 'login' ? 'Create account' : 'Have an account? Login'}</button>
    </form>
  )
}
