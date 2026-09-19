import { useEffect, useState } from 'react';
import { Button, Layout, Menu, message, Spin, Typography } from 'antd';
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { api, clearCsrf, setCsrf } from './api';
import { Applications, ApplicationCreate, ApplicationDetail, Jobs, Questions, AISettings } from './HR';
import Candidate from './Candidate';

const { Header, Sider, Content } = Layout;

function Login({ onLogin }: { onLogin: () => void }) {
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true);
    try {
      const result = await api<{ csrf_token: string }>('/hr/session', { method: 'POST', body: JSON.stringify({ password }) });
      setCsrf(result.csrf_token); setPassword(''); onLogin();
    } catch (error) { message.error((error as Error).message); }
    finally { setBusy(false); }
  };
  return <div className="login"><div className="login-card">
    <Typography.Title level={2}>招聘测评 · HR</Typography.Title>
    <Typography.Paragraph type="secondary">输入后台口令，查看应聘档案与测评记录。</Typography.Paragraph>
    <form onSubmit={submit}><input className="password-input" type="password" autoComplete="current-password"
      value={password} onChange={e => setPassword(e.target.value)} placeholder="后台口令" required />
      <Button type="primary" htmlType="submit" loading={busy} block size="large">登录</Button></form>
  </div></div>;
}

function HRApp() {
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    api<{ csrf_token: string }>('/hr/session').then(data => { setCsrf(data.csrf_token); setAuthorized(true); })
      .catch(() => { clearCsrf(); setAuthorized(false); });
  }, []);
  if (authorized === null) return <div className="center"><Spin size="large" /></div>;
  if (!authorized) return <Login onLogin={() => setAuthorized(true)} />;
  const logout = async () => {
    try { await api('/hr/session', { method: 'DELETE' }); } finally { clearCsrf(); setAuthorized(false); navigate('/applications'); }
  };
  const key = location.pathname.startsWith('/jobs') ? 'jobs' : location.pathname.startsWith('/questions') ? 'questions'
    : location.pathname.startsWith('/settings') ? 'settings' : 'applications';
  return <Layout className="shell">
    <Sider breakpoint="lg" collapsedWidth="0" width={215} theme="light" className="sider">
      <div className="brand">人才测评<span>MVP</span></div>
      <Menu selectedKeys={[key]} mode="inline" items={[
        { key: 'applications', label: <Link to="/applications">应聘管理</Link> },
        { key: 'jobs', label: <Link to="/jobs">岗位管理</Link> },
        { key: 'questions', label: <Link to="/questions">题库管理</Link> },
        { key: 'settings', label: <Link to="/settings/ai">AI 配置</Link> },
      ]} />
    </Sider>
    <Layout><Header className="topbar"><span>结构化招聘测评</span><Button type="link" onClick={logout}>退出登录</Button></Header>
      <Content className="content"><Routes>
        <Route path="/applications" element={<Applications />} />
        <Route path="/applications/new" element={<ApplicationCreate />} />
        <Route path="/applications/:id" element={<ApplicationDetail />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/questions" element={<Questions />} />
        <Route path="/settings/ai" element={<AISettings />} />
        <Route path="*" element={<Navigate to="/applications" replace />} />
      </Routes></Content>
    </Layout>
  </Layout>;
}

export default function App() {
  return <Routes>
    <Route path="/assessment/:token" element={<Candidate />} />
    <Route path="/*" element={<HRApp />} />
  </Routes>;
}
