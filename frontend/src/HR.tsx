import { useEffect, useState } from 'react';
import {
  Alert, Button, Card, Col, Descriptions, Divider, Form, Input, InputNumber, List, message,
  Modal, Popconfirm, Row, Select, Space, Spin, Statistic, Switch, Table, Tag, Typography, Upload,
} from 'antd';
import type { UploadFile } from 'antd';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, json } from './api';

const statusText: Record<string, string> = {
  screening: '简历初筛中', screening_failed: '初筛失败', review_pending: '待 HR 审核', ready: '待首次打开',
  exam_in_progress: '笔试中', interview_in_progress: 'AI 问答中', practical_in_progress: 'AI 编程实操中', suspended: '已挂起',
  scoring: '评分中', completed: '已完成', expired: '链接已过期', cancelled: '已取消',
};
const questionTypeText: Record<string, string> = {
  SINGLE_CHOICE: '单选题', MULTIPLE_CHOICE: '多选题', SHORT_ANSWER: '简答题',
};
const fmt = (value?: string) => value ? new Date(value + (value.endsWith('Z') ? '' : 'Z')).toLocaleString('zh-CN') : '—';
const error = (e: unknown) => message.error((e as Error).message);
const sourceText = (ref: string) => ref === 'resume' ? '简历'
  : ref.startsWith('objective:') ? `客观错题 #${ref.slice(10)}`
  : ref.startsWith('round:') ? `第 ${ref.slice(6)} 轮回答` : ref;

export function Applications() {
  const [rows, setRows] = useState<any[]>([]);
  const [jobs, setJobs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [jobId, setJobId] = useState<number>();
  const [status, setStatus] = useState<string>();
  const refresh = () => { setLoading(true); api<any[]>('/applications?' + new URLSearchParams({
    q: query, ...(jobId ? { job_id: String(jobId) } : {}), ...(status ? { status } : {}),
  })).then(setRows).catch(error).finally(() => setLoading(false)); };
  useEffect(() => { api<any[]>('/jobs').then(setJobs).catch(error); }, []);
  useEffect(refresh, [query, jobId, status]);
  return <div><div className="page-heading"><div><Typography.Title level={2}>应聘管理</Typography.Title><p>从简历初筛到完整测评，查看每份档案的进展。</p></div>
    <Link to="/applications/new"><Button type="primary" size="large">新建应聘</Button></Link></div>
    <Card><Space wrap className="filters"><Input.Search placeholder="候选人姓名" allowClear onSearch={setQuery} style={{ width: 210 }} />
      <Select placeholder="所有岗位" allowClear style={{ width: 190 }} value={jobId} onChange={setJobId}
        options={jobs.map(j => ({ label: j.name, value: j.id }))} />
      <Select placeholder="所有状态" allowClear style={{ width: 170 }} value={status} onChange={setStatus}
        options={Object.entries(statusText).map(([value, label]) => ({ value, label }))} />
      <Button onClick={refresh}>刷新</Button></Space>
      <Table rowKey="id" dataSource={rows} loading={loading} pagination={{ pageSize: 10 }} scroll={{ x: 900 }} columns={[
        { title: '候选人', dataIndex: 'candidate_name', render: (v, r) => <Link to={'/applications/' + r.id}>{v}</Link> },
        { title: '岗位', dataIndex: 'job_name' },
        { title: '联系方式', render: (_, r) => r.candidate_email || r.candidate_phone || '—' },
        { title: '状态', dataIndex: 'status', render: (v) => <Tag color={v === 'completed' ? 'green' : v === 'suspended' ? 'orange' : 'blue'}>{statusText[v] || v}</Tag> },
        { title: '初筛分', dataIndex: 'screening_score', render: v => v ?? '—' },
        { title: '综合分', dataIndex: 'overall_score', render: v => v ?? '—' },
        { title: '创建时间', dataIndex: 'created_at', render: fmt },
        { title: '操作', render: (_, r) => <Link to={'/applications/' + r.id}>查看</Link> },
      ]} /></Card></div>;
}

export function ApplicationCreate() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [file, setFile] = useState<UploadFile[]>([]);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  useEffect(() => { api<any[]>('/jobs').then(setJobs).catch(error); }, []);
  const submit = async (values: any) => {
    if (!file[0]?.originFileObj) { message.error('请上传 PDF 或 DOCX 简历'); return; }
    const form = new FormData();
    for (const key of ['candidate_name', 'candidate_email', 'candidate_phone', 'job_id']) {
      if (values[key] !== undefined) form.append(key, String(values[key]));
    }
    form.append('resume', file[0].originFileObj);
    setBusy(true);
    try {
      const result = await api<any>('/applications', { method: 'POST', body: form });
      message.success('档案已创建，正在进行简历初筛'); navigate('/applications/' + result.id);
    } catch (e) { error(e); } finally { setBusy(false); }
  };
  return <div className="narrow"><div className="page-heading"><div><Typography.Title level={2}>新建应聘</Typography.Title><p>上传简历后先由 AI 初筛，HR 审核后再生成候选人链接。</p></div></div>
    <Card><Form layout="vertical" onFinish={submit} initialValues={{ candidate_email: '', candidate_phone: '' }}>
      <Form.Item label="候选人姓名" name="candidate_name" rules={[{ required: true }]}><Input /></Form.Item>
      <Row gutter={16}><Col span={12}><Form.Item label="邮箱" name="candidate_email"><Input /></Form.Item></Col>
        <Col span={12}><Form.Item label="手机号" name="candidate_phone"><Input /></Form.Item></Col></Row>
      <Form.Item label="招聘岗位" name="job_id" rules={[{ required: true }]}><Select options={jobs.filter(j => j.enabled).map(j => ({ label: j.name, value: j.id }))} /></Form.Item>
      <Form.Item label="简历（PDF / DOCX，≤ 5 MB）" required><Upload beforeUpload={() => false} maxCount={1} accept=".pdf,.docx"
        fileList={file} onChange={({ fileList }) => setFile(fileList)}><Button>选择文件</Button></Upload></Form.Item>
      <Button type="primary" htmlType="submit" loading={busy}>创建并开始初筛</Button>
    </Form></Card></div>;
}

export function ApplicationDetail() {
  const { id } = useParams();
  const [data, setData] = useState<any>();
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState('');
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const refresh = () => api<any>('/applications/' + id).then(d => { setData(d); setText(d.resume_text); }).catch(error);
  useEffect(() => { refresh(); const timer = setInterval(refresh, 8000); return () => clearInterval(timer); }, [id]);
  const action = async (path: string, body?: unknown) => {
    setBusy(true);
    try { const result = await api<any>('/applications/' + id + path, { method: 'POST', ...(body ? { body: json(body) } : {}) });
      if (result.url) { setLink(result.url); message.success('链接已生成，请复制并发送'); }
      else message.success('操作完成'); await refresh();
    } catch (e) { error(e); } finally { setBusy(false); }
  };
  if (!data) return <div className="center"><Spin /></div>;
  const screen = data.screenings[0]; const result = data.results[0];
  return <div><div className="page-heading"><div><Typography.Text type="secondary"><Link to="/applications">应聘管理</Link> / 档案详情</Typography.Text>
    <Typography.Title level={2}>{data.candidate_name} <Tag>{statusText[data.status] || data.status}</Tag></Typography.Title>
    <p>{data.job_name} · 创建于 {fmt(data.created_at)}</p></div>
    <Space wrap>
      {data.status === 'review_pending' && <Button type="primary" loading={busy} onClick={() => action('/issue-link')}>生成测评链接</Button>}
      {data.status === 'expired' && <Button type="primary" loading={busy} onClick={() => action('/regenerate-token')}>重新生成链接</Button>}
      {data.status === 'suspended' && <Button type="primary" loading={busy} onClick={() => action('/resume-assessment')}>修复完成，重置计时并恢复</Button>}
      {data.status === 'screening_failed' && !!data.resume_text && <Button loading={busy} onClick={() => action('/screening/retry')}>重试初筛</Button>}
      {['review_pending', 'ready', 'expired', 'screening_failed'].includes(data.status) && !data.started_at &&
        <Popconfirm title="按当前岗位 JD 重新初筛？" description="未打开的旧链接和已预抽题目会失效，初筛完成后需重新生成链接。"
          onConfirm={() => action('/rescreen-current-job')}><Button loading={busy}>按当前岗位重新匹配</Button></Popconfirm>}
      {(data.status === 'scoring' && data.scoring_error || data.status === 'completed') && <Button loading={busy} onClick={() => action('/rescore')}>按现有答案重新评分</Button>}
      {data.status === 'completed' && <Popconfirm title="让候选人重新答题？" description="旧答案和评分会存档，并生成新链接；新链接首次打开后重新计时 3 小时。"
        onConfirm={() => action('/retake')}><Button type="primary" loading={busy}>重新答题并生成链接</Button></Popconfirm>}
      {!['completed', 'cancelled'].includes(data.status) && <Popconfirm title="确定取消本次应聘？" onConfirm={() => action('/cancel', { reason: 'HR 决定不推进或取消' })}><Button danger>不推进 / 取消</Button></Popconfirm>}
    </Space></div>
    {link && <Alert className="block" type="success" showIcon message="候选人链接（只显示这一次）"
      description={<Space wrap><Typography.Text copyable>{link}</Typography.Text></Space>} />}
    {data.assessment_round > 1 && <Alert className="block" type="info" showIcon
      message={`当前为第 ${data.assessment_round} 次测评；旧答案和评分见下方历史记录。`} />}
    <Row gutter={[16, 16]}><Col xs={24} md={16}>
      <Card title="简历初筛" className="block">{screen ? <><Space align="center"><Statistic title="初筛分" value={screen.score} suffix="/ 100" /><Tag color="green">第 {screen.version} 版简历</Tag></Space>
        {screen.dimensions && Object.keys(screen.dimensions).length > 0 && <Descriptions className="top-gap" size="small" column={2} items={[
          ['manufacturing_domain', '制造业场景'], ['ai_solution', 'AI 与 Agent'],
          ['mvp_delivery', 'MVP 与工程交付'], ['stakeholder_governance', '沟通与治理'],
        ].map(([key, label]) => ({ key, label, children: `${screen.dimensions[key] ?? '—'} / 100` }))} />}
        <Typography.Paragraph className="top-gap">{screen.comment}</Typography.Paragraph>
        <List size="small" dataSource={screen.evidence} renderItem={(item: string) => <List.Item>{item}</List.Item>} />
        <Typography.Text type="secondary">初筛仅供 HR 决定是否推进。</Typography.Text></>
        : <Alert type={data.screening_error ? 'error' : 'info'}
          message={data.screening_error ? '初筛失败' : '初筛进行中'}
          description={data.screening_error ? (data.screening_error_detail || '请检查简历文本或 AI 配置后重试。') : undefined} />}</Card>
      <Card title="笔试结果" className="block">{data.questions.length ? <List dataSource={data.questions} renderItem={(q: any) =>
        <List.Item><div><b>{q.order_no}. {q.content}</b><div>候选人：{JSON.stringify(q.answer ?? '未答')}</div>
          <div className="muted">实际难度 {q.difficulty} / 5{q.target_difficulty && q.target_difficulty !== q.difficulty ? `（目标难度 ${q.target_difficulty}，题库取最近难度）` : ''}</div>
          <div className="muted">参考：{q.reference_answer || JSON.stringify(q.correct_answer)}</div>
          {q.is_correct !== null && <Tag color={q.is_correct ? 'green' : 'red'}>{q.is_correct ? '正确' : '错误'}</Tag>}
          {q.objective_score !== null && <Tag>客观题得分 {q.objective_score}/{q.score_points}</Tag>}</div></List.Item>} /> : '链接发放后抽题'}</Card>
      <Card title="AI 三轮问答" className="block">{data.turns.length ? <List dataSource={data.turns} renderItem={(t: any) =>
        <List.Item><div><b>第 {t.round_no} 轮 · {t.question}</b>
          {(t.focus_area || t.source_refs?.length) && <div className="muted">{t.focus_area && `考察点：${t.focus_area}`}
            {t.source_refs?.length ? ` · 依据：${t.source_refs.map(sourceText).join('、')}` : ''}</div>}
          {t.round_no === 2 && t.first_answer_complete !== null && <div className="muted">
            首答判断：{t.first_answer_complete ? '充分，切换考察点' : `需要追问：${t.answer_gap || '细节不足'}`}</div>}
          <p>候选人：{t.answer || '未答'}</p></div></List.Item>} /> : '尚未开始'}</Card>
      <Card title="AI 编程实操" className="block">{data.practical &&
        (data.practical.attempt_count > 0 || ['practical_in_progress', 'scoring', 'completed'].includes(data.status)) ? <>
        <Space wrap><Statistic title="最高分" value={data.practical.best_score} suffix="/ 100" />
          <Tag color="blue">已提交 {data.practical.attempt_count} / 5 次</Tag>
          {data.practical.finalized_at && <Tag color="green">已确认</Tag>}</Space>
        {!!Object.keys(data.practical.breakdown || {}).length && <Descriptions className="top-gap" size="small" column={2}
          items={Object.entries(data.practical.breakdown).map(([key, value]) => ({ key, label: key, children: String(value) }))} />}
        {!!data.practical.feedback?.length && <Alert className="top-gap" type="warning" message="未通过分项" description={data.practical.feedback.join('；')} />}
        {data.practical.has_submission && <a className="top-gap" style={{ display: 'inline-block' }}
          href={'/api/applications/' + id + '/practical/submission'}>下载最高分提交包</a>}
      </> : <Typography.Text type="secondary">完成三轮问答后生成候选人专属题目包。</Typography.Text>}</Card>
      <Card title="AI 辅助评价" className="block">{data.scoring_error && <Alert type="error" message={data.scoring_error} className="block" />}
        {result ? <><Row gutter={16}><Col flex="1"><Statistic title="综合分" value={result.overall_score} /></Col>
          <Col flex="1"><Statistic title="笔试" value={result.exam_score} /></Col><Col flex="1"><Statistic title="实操" value={result.practical_score} /></Col>
          <Col flex="1"><Statistic title="问答" value={result.interview_score} /></Col><Col flex="1"><Statistic title="简历" value={result.resume_score} /></Col></Row>
          {result.incomplete_reason && <Alert type="warning" message={result.incomplete_reason} className="top-gap" />}
          <Divider />{result.summary}<Descriptions className="top-gap" column={2} size="small" items={Object.entries(result.dimensions).map(([key, value]) => ({ key, label: key, children: String(value) }))} />
          <Typography.Title level={5}>优势</Typography.Title><List size="small" dataSource={result.strengths} renderItem={(v: string) => <List.Item>{v}</List.Item>} />
          <Typography.Title level={5}>不足与待确认</Typography.Title><List size="small" dataSource={[...result.weaknesses, ...result.risks]} renderItem={(v: string) => <List.Item>{v}</List.Item>} />
          <Typography.Title level={5}>评分证据</Typography.Title><List size="small" dataSource={result.evidence} renderItem={(v: any) => <List.Item>{v.source} · {v.summary}</List.Item>} />
          {data.results.length > 1 && <Typography.Text type="secondary">共 {data.results.length} 次评分，显示最新结果；历史仍已存档。</Typography.Text>}
        </> : <Typography.Text type="secondary">候选人提交后显示。</Typography.Text>}</Card>
      {!!data.past_attempts?.length && <Card title="历史测评" className="block"><List dataSource={data.past_attempts} renderItem={(attempt: any) =>
        <List.Item><div><b>第 {attempt.assessment_round} 次测评</b> · 完成于 {fmt(attempt.completed_at)}
          {attempt.results[0] && <p>综合分 {attempt.results[0].overall_score} · 笔试 {attempt.results[0].exam_score} · 实操 {attempt.results[0].practical_score} · 问答 {attempt.results[0].interview_score}</p>}
          {attempt.practical && Object.keys(attempt.practical).length > 0 && <p>实操提交 {attempt.practical.attempt_count} 次，最高 {attempt.practical.score} 分</p>}
          <Typography.Text type="secondary">{attempt.results[0]?.summary || '无评分结果'}</Typography.Text>
          <details><summary>查看旧答案与问答</summary>
            <List size="small" dataSource={attempt.answers} renderItem={(a: any) =>
              <List.Item>{a.order_no}. {a.question} · 难度 {a.difficulty ?? '—'} · 回答：{JSON.stringify(a.answer ?? '未答')}
                {a.is_correct !== null && a.is_correct !== undefined ? ` · ${a.is_correct ? '正确' : '错误'}` : ''}</List.Item>} />
            <List size="small" dataSource={attempt.turns} renderItem={(t: any) =>
              <List.Item>第 {t.round_no} 轮：{t.question} · 回答：{t.answer || '未答'}</List.Item>} />
          </details></div></List.Item>} /></Card>}
    </Col><Col xs={24} md={8}>
      <Card title="档案信息" className="block"><Descriptions column={1} size="small" items={[
        { key: 'email', label: '邮箱', children: data.candidate_email || '—' },
        { key: 'phone', label: '手机', children: data.candidate_phone || '—' },
        { key: 'start', label: '首次打开', children: fmt(data.started_at) },
        { key: 'deadline', label: '截止时间', children: fmt(data.deadline_at) },
        { key: 'finish', label: '完成时间', children: fmt(data.completed_at) },
      ]} /><a href={'/api/applications/' + id + '/resume'} target="_blank" rel="noreferrer">下载原始简历</a></Card>
      <Card title="本次岗位 JD" className="block"><div className="pre">{data.job_jd_snapshot}</div></Card>
      <Card title="简历解析文本" className="block"><div className="pre">{data.resume_text || '解析失败，请手工补充'}</div>
        {['review_pending', 'screening_failed'].includes(data.status) && <Button className="top-gap" onClick={() => setEditing(true)}>编辑并重新初筛</Button>}</Card>
      <Card title="操作记录" className="block"><List size="small" dataSource={data.events} renderItem={(e: any) =>
        <List.Item><div>{e.action} <Tag>{e.actor}</Tag><div className="muted">{fmt(e.created_at)} {e.reason}</div></div></List.Item>} /></Card>
    </Col></Row>
    <Modal title="修改简历解析文本" open={editing} onCancel={() => setEditing(false)} width={760} onOk={async () => {
      try { await api('/applications/' + id + '/resume-text', { method: 'PUT', body: json({ text }) });
        setEditing(false); message.success('已重新开始初筛'); refresh(); } catch (e) { error(e); }
    }}><Input.TextArea rows={15} value={text} onChange={e => setText(e.target.value)} /></Modal>
  </div>;
}

export function Jobs() {
  const [rows, setRows] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<any>();
  const [rules, setRules] = useState<any[]>([]);
  const [form] = Form.useForm();
  const refresh = () => api<any[]>('/jobs').then(setRows).catch(error);
  useEffect(() => { refresh(); }, []);
  const edit = (job?: any) => { setEditing(job); form.setFieldsValue(job || { name: '', department: '', description: '', jd: '', enabled: true });
    setRules(job?.rules?.map((r: any) => ({ ...r })) || []); setOpen(true); };
  const submit = async (values: any) => {
    try {
      const job = await api<any>(editing ? '/jobs/' + editing.id : '/jobs', { method: editing ? 'PUT' : 'POST', body: json(values) });
      await api('/jobs/' + job.id + '/question-rules', { method: 'PUT', body: json(rules.map(({ category, count, min_difficulty, max_difficulty }) =>
        ({ category, count: Number(count), min_difficulty: Number(min_difficulty), max_difficulty: Number(max_difficulty) }))) });
      message.success('岗位已保存'); setOpen(false); refresh();
    } catch (e) { error(e); }
  };
  return <><div className="page-heading"><div><Typography.Title level={2}>岗位管理</Typography.Title><p>维护 JD 和按分类、难度抽题的规则。</p></div><Button type="primary" onClick={() => edit()}>新建岗位</Button></div>
    <Card><Table rowKey="id" dataSource={rows} columns={[
      { title: '岗位', dataIndex: 'name' }, { title: '部门', dataIndex: 'department' },
      { title: '状态', dataIndex: 'enabled', render: v => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag> },
      { title: '抽题数', dataIndex: 'rules', render: (r: any[]) => r.reduce((n, x) => n + x.count, 0) },
      { title: '操作', render: (_, r) => <Button type="link" onClick={() => edit(r)}>编辑</Button> },
    ]} /></Card>
    <Modal title={editing ? '编辑岗位' : '新建岗位'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} width={800}>
      <Form form={form} layout="vertical" onFinish={submit}><Row gutter={16}><Col span={12}><Form.Item name="name" label="岗位名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
        <Col span={12}><Form.Item name="department" label="部门"><Input /></Form.Item></Col></Row>
        <Form.Item name="jd" label="岗位 JD" rules={[{ required: true }]}><Input.TextArea rows={7} /></Form.Item>
        <Form.Item name="description" label="说明"><Input.TextArea rows={2} /></Form.Item>
        <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item></Form>
      <Divider>抽题规则</Divider>{rules.map((r, i) => <Space key={i} wrap className="rule-row">
        <Input placeholder="分类" value={r.category} onChange={e => setRules(rules.map((x, n) => n === i ? { ...x, category: e.target.value } : x))} style={{ width: 140 }} />
        <InputNumber min={1} max={100} value={r.count} onChange={v => setRules(rules.map((x, n) => n === i ? { ...x, count: v } : x))} addonBefore="题数" />
        <InputNumber min={1} max={5} value={r.min_difficulty} onChange={v => setRules(rules.map((x, n) => n === i ? { ...x, min_difficulty: v } : x))} addonBefore="最低" />
        <InputNumber min={1} max={5} value={r.max_difficulty} onChange={v => setRules(rules.map((x, n) => n === i ? { ...x, max_difficulty: v } : x))} addonBefore="最高" />
        <Button danger onClick={() => setRules(rules.filter((_, n) => n !== i))}>移除</Button></Space>)}
      <Button onClick={() => setRules([...rules, { category: '', count: 1, min_difficulty: 1, max_difficulty: 5 }])}>添加规则</Button>
      <Typography.Paragraph type="secondary" className="top-gap">规则总计 5 道、各分类难度范围均为 1–5 时，候选人逐题作答并自适应升降难度。</Typography.Paragraph>
    </Modal>
  </>;
}

export function Questions() {
  const [rows, setRows] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<any>();
  const [form] = Form.useForm();
  const refresh = () => api<any[]>('/questions').then(setRows).catch(error);
  useEffect(() => { refresh(); }, []);
  const edit = (q?: any) => { setEditing(q); form.resetFields(); form.setFieldsValue(q ? { ...q, options_text: q.options?.join('\n'),
    answer_text: Array.isArray(q.correct_answer) ? q.correct_answer.join(',') : q.correct_answer } :
    { type: 'SINGLE_CHOICE', difficulty: 3, score_points: 10, enabled: true }); setOpen(true); };
  const submit = async (values: any) => {
    const { options_text, answer_text, ...rest } = values;
    const payload = { ...rest, options: options_text?.split('\n').map((v: string) => v.trim()).filter(Boolean) || null,
      correct_answer: rest.type === 'MULTIPLE_CHOICE' ? answer_text?.split(',').map((v: string) => v.trim()).filter(Boolean) : answer_text || null };
    try { await api(editing ? '/questions/' + editing.id : '/questions', { method: editing ? 'PUT' : 'POST', body: json(payload) });
      setOpen(false); message.success('题目已保存'); refresh(); } catch (e) { error(e); }
  };
  return <><div className="page-heading"><div><Typography.Title level={2}>题库管理</Typography.Title><p>题目按岗位规则抽取，发链接时保存快照。</p></div><Button type="primary" onClick={() => edit()}>新建题目</Button></div>
    <Card><Table rowKey="id" dataSource={rows} pagination={{ pageSize: 10 }} columns={[
      { title: '标题', dataIndex: 'title' }, { title: '类型', dataIndex: 'type', render: (v: string) => questionTypeText[v] || v }, { title: '分类', dataIndex: 'category' },
      { title: '难度', dataIndex: 'difficulty' }, { title: '状态', dataIndex: 'enabled', render: v => v ? '启用' : '停用' },
      { title: '操作', render: (_, r) => <Button type="link" onClick={() => edit(r)}>编辑</Button> },
    ]} /></Card>
    <Modal title={editing ? '编辑题目' : '新建题目'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} width={760}>
      <Form form={form} layout="vertical" onFinish={submit}><Form.Item name="title" label="标题" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="content" label="题目内容" rules={[{ required: true }]}><Input.TextArea rows={3} /></Form.Item>
        <Row gutter={12}><Col span={8}><Form.Item name="type" label="题型"><Select options={Object.entries(questionTypeText).map(([value, label]) => ({ value, label }))} /></Form.Item></Col>
          <Col span={8}><Form.Item name="category" label="分类" rules={[{ required: true }]}><Input placeholder="例如 Python" /></Form.Item></Col>
          <Col span={8}><Form.Item name="difficulty" label="难度"><InputNumber min={1} max={5} /></Form.Item></Col></Row>
        <Form.Item name="options_text" label="选项（一行一个；简答题留空）"><Input.TextArea rows={4} /></Form.Item>
        <Form.Item name="answer_text" label="正确选项（多选用逗号分隔）"><Input /></Form.Item>
        <Form.Item name="reference_answer" label="参考答案"><Input.TextArea rows={2} /></Form.Item>
        <Form.Item name="scoring_guide" label="评分要点"><Input.TextArea rows={2} /></Form.Item>
        <Row gutter={12}><Col span={12}><Form.Item name="score_points" label="分值"><InputNumber min={1} /></Form.Item></Col>
          <Col span={12}><Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item></Col></Row></Form>
    </Modal></>;
}

export function AISettings() {
  const [form] = Form.useForm();
  const [version, setVersion] = useState(0);
  const [configured, setConfigured] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testStatus, setTestStatus] = useState<{ type: 'info' | 'success' | 'error'; message: string; description: string }>();
  useEffect(() => { api<any>('/ai-config').then(d => { form.setFieldsValue({ ...d, round1: d.round_prompts?.[0] || '',
    round2: d.round_prompts?.[1] || '', round3: d.round_prompts?.[2] || '' }); setVersion(d.version); setConfigured(d.api_key_configured); }).catch(error); }, []);
  const save = async (values: any) => {
    const { round1, round2, round3, ...rest } = values;
    try { const d = await api<any>('/ai-config', { method: 'PUT', body: json({ ...rest, round_prompts: [round1 || '', round2 || '', round3 || ''] }) });
      setVersion(d.version); setTestStatus(undefined); message.success('已创建不可变配置版本 ' + d.version); } catch (e) { error(e); }
  };
  const testConnection = async () => {
    if (!configured) {
      setTestStatus({ type: 'error', message: '模型连接失败', description: '服务端未配置 DEEPSEEK_API_KEY。' });
      return;
    }
    setTesting(true);
    setTestStatus({ type: 'info', message: '正在测试模型连接', description: '正在请求当前已保存的配置，最多等待约 30 秒。' });
    try {
      const result = await api<{ ok: boolean; model: string }>('/ai-config/test', {
        method: 'POST', signal: AbortSignal.timeout(30000),
      });
      setTestStatus(result.ok
        ? { type: 'success', message: '模型连接成功', description: `${result.model} 已返回有效测试结果。` }
        : { type: 'error', message: '模型连接失败', description: `${result.model} 返回的测试结果不符合预期。` });
    } catch (e) {
      const timeout = e instanceof Error && (e.name === 'TimeoutError' || e.name === 'AbortError');
      setTestStatus({ type: 'error', message: '模型连接失败',
        description: timeout ? '测试请求超时，请检查模型服务和网络后重试。' : (e as Error).message });
    } finally { setTesting(false); }
  };
  return <div className="narrow"><div className="page-heading"><div><Typography.Title level={2}>AI 配置</Typography.Title><p>当前版本 {version}。修改会创建新版本，历史评分继续引用旧配置。</p></div></div>
    <Alert className="block" type={configured ? 'success' : 'warning'} message={configured ? 'API Key 已在服务端环境中配置' : '服务端未配置 DEEPSEEK_API_KEY'}
      description="密钥不会显示在网页，也不会保存在配置记录中。" />
    <Card><Form form={form} layout="vertical" onFinish={save}>
      <Row gutter={12}><Col span={12}><Form.Item name="name" label="配置名称"><Input /></Form.Item></Col>
        <Col span={12}><Form.Item name="model" label="模型" rules={[{ required: true }]}><Input /></Form.Item></Col></Row>
      <Form.Item name="base_url" label="API Base URL" rules={[{ required: true }]}><Input /></Form.Item>
      <Row gutter={12}><Col span={12}><Form.Item name="temperature" label="Temperature"><InputNumber min={0} max={2} step={0.1} /></Form.Item></Col>
        <Col span={12}><Form.Item name="max_tokens" label="Max Tokens"><InputNumber min={100} max={8000} /></Form.Item></Col></Row>
      {[['screening_prompt', '简历初筛 Prompt'], ['round1', '第一轮规则'], ['round2', '第二轮规则'],
        ['round3', '第三轮规则'], ['scoring_prompt', '最终评分 Prompt']].map(([name, label]) =>
        <Form.Item key={name} name={name} label={label}><Input.TextArea rows={3} placeholder="留空使用系统默认规则" /></Form.Item>)}
      <Space><Button type="primary" htmlType="submit">保存为新版本</Button>
        <Button loading={testing} onClick={testConnection}>测试模型连接</Button></Space>
      {testStatus && <Alert className="top-gap" showIcon type={testStatus.type}
        message={testStatus.message} description={testStatus.description} />}
    </Form></Card></div>;
}
