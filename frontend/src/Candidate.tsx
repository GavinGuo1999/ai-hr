import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Input, Progress, Radio, Checkbox, Space, Spin, Steps, Tag, Typography, Upload, message } from 'antd';
import type { UploadFile } from 'antd';
import { useParams } from 'react-router-dom';
import { api, json } from './api';

const parseTime = (value?: string) => value ? Date.parse(value + (value.endsWith('Z') ? '' : 'Z')) : 0;

export default function Candidate() {
  const { token } = useParams();
  const base = '/candidate/' + encodeURIComponent(token || '');
  const [state, setState] = useState<any>();
  const [exam, setExam] = useState<any>();
  const [index, setIndex] = useState(0);
  const [value, setValue] = useState<any>('');
  const [busy, setBusy] = useState(false);
  const [remaining, setRemaining] = useState(3 * 3600);
  const [serverOffset, setServerOffset] = useState(0);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const currentValue = useRef<any>('');
  const [fatal, setFatal] = useState('');
  const [objectiveFeedback, setObjectiveFeedback] = useState<{ correct: boolean; orderNo: number; nextDifficulty: number | null }>();
  const [practical, setPractical] = useState<any>();
  const [packageFile, setPackageFile] = useState<UploadFile[]>([]);

  const sync = (data: any) => {
    setState(data);
    if (data.server_now) setServerOffset(parseTime(data.server_now) - Date.now());
  };
  const refresh = async () => {
    try { sync(await api(base)); setFatal(''); } catch (e) { setFatal((e as Error).message); }
  };
  useEffect(() => { refresh(); const timer = setInterval(refresh, 6000); return () => clearInterval(timer); }, [token]);
  useEffect(() => {
    if (state?.status !== 'exam_in_progress') return;
    api<any>(base + '/exam').then(setExam).catch(e => message.error((e as Error).message));
  }, [state?.status, token]);
  useEffect(() => {
    if (state?.status !== 'practical_in_progress') return;
    api<any>(base + '/practical').then(setPractical).catch(e => message.error((e as Error).message));
  }, [state?.status, token]);
  useEffect(() => {
    if (exam?.adaptive) {
      currentValue.current = ''; setValue('');
      return;
    }
    if (!exam?.questions?.[index]) return;
    const next = exam.questions[index].answer ?? (exam.questions[index].type === 'MULTIPLE_CHOICE' ? [] : '');
    currentValue.current = next; setValue(next);
  }, [exam, index]);
  useEffect(() => {
    const tick = () => {
      if (!state?.deadline_at) return;
      setRemaining(Math.max(0, Math.ceil((parseTime(state.deadline_at) - (Date.now() + serverOffset)) / 1000)));
    };
    tick(); const timer = setInterval(tick, 1000); return () => clearInterval(timer);
  }, [state?.deadline_at, serverOffset]);
  useEffect(() => () => { if (saveTimer.current) clearTimeout(saveTimer.current); }, []);
  const save = async (answer = currentValue.current) => {
    const q = exam?.questions?.[index];
    if (!q || state?.status !== 'exam_in_progress') return;
    await api(base + '/answers/' + q.id, { method: 'PUT', body: json({ answer }) });
    q.answer = answer;
  };
  const change = (next: any) => {
    currentValue.current = next; setValue(next);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => save(next).catch(e => message.error((e as Error).message)), 700);
  };
  const move = async (next: number) => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    try { await save(); setIndex(next); } catch (e) { message.error((e as Error).message); await refresh(); }
  };
  const submitExam = async () => {
    setBusy(true);
    try { if (saveTimer.current) clearTimeout(saveTimer.current); await save(); sync(await api(base + '/exam/submit', { method: 'POST' }));
      message.success('笔试已提交'); } catch (e) { message.error((e as Error).message); await refresh(); }
    finally { setBusy(false); }
  };
  const submitObjective = async () => {
    const current = exam?.current_question;
    if (!current || !value || busy) return;
    setBusy(true);
    try {
      const result = await api<any>(base + '/exam/objective/submit', {
        method: 'POST', body: json({ question_id: current.id, answer: value }),
      });
      setObjectiveFeedback({ correct: result.correct, orderNo: current.order_no,
        nextDifficulty: result.next_difficulty });
      sync(result.state);
      if (result.state.status === 'exam_in_progress') setExam(await api(base + '/exam'));
    } catch (e) { message.error((e as Error).message); await refresh(); }
    finally { setBusy(false); }
  };
  const [reply, setReply] = useState('');
  const submitReply = async () => {
    if (!state?.current_turn || !reply.trim()) return;
    setBusy(true);
    try { sync(await api(base + '/interview/answer', { method: 'POST', body: json({ turn_id: state.current_turn.id, answer: reply }) }));
      setReply(''); } catch (e) { message.error((e as Error).message); await refresh(); }
    finally { setBusy(false); }
  };
  const suspend = async () => {
    setBusy(true);
    try { sync(await api(base + '/suspend', { method: 'POST' })); } catch (e) { message.error((e as Error).message); }
    finally { setBusy(false); }
  };
  const submitPractical = async () => {
    if (!packageFile[0]?.originFileObj) { message.error('请选择 ZIP 提交包'); return; }
    const form = new FormData(); form.append('package', packageFile[0].originFileObj);
    setBusy(true);
    try {
      const result = await api<any>(base + '/practical/submissions', { method: 'POST', body: form });
      setPractical(result); setPackageFile([]); message.success(`本次 ${result.score} 分，已保留最高分 ${result.best_score}`);
    } catch (e) { message.error((e as Error).message); }
    finally { setBusy(false); }
  };
  const finalizePractical = async () => {
    setBusy(true);
    try { sync(await api(base + '/practical/finalize', { method: 'POST' })); }
    catch (e) { message.error((e as Error).message); await refresh(); }
    finally { setBusy(false); }
  };
  const clock = `${String(Math.floor(remaining / 3600)).padStart(2, '0')}:${String(Math.floor(remaining % 3600 / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`;
  const q = exam?.questions?.[index];
  const adaptiveQuestion = exam?.current_question;
  const bulbs = exam?.adaptive && <div className="bulb-row" aria-label="客观题进度">{exam.progress.map((step: any) => {
    const result = objectiveFeedback?.orderNo === step.order_no
      ? (objectiveFeedback?.correct ? 'correct' : 'wrong') : step.result;
    return <div key={step.order_no} className={'bulb ' + result} title={`第 ${step.order_no} 题${step.difficulty ? ` · 难度 ${step.difficulty}` : ''} · ${result === 'correct' ? '正确' : result === 'wrong' ? '错误' : '未作答'}`}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 21h6v-2H9v2Zm3-19a7 7 0 0 0-4 12.75V17h8v-2.25A7 7 0 0 0 12 2Zm2.6 11.4-.6.45V15h-4v-1.15l-.6-.45a5 5 0 1 1 5.2 0Z" /></svg>
      <span>{step.order_no}</span></div>;
  })}</div>;

  return <div className="candidate-shell"><header className="candidate-header"><div className="candidate-brand">招聘测评</div>
    {state?.deadline_at && ['exam_in_progress', 'interview_in_progress', 'practical_in_progress'].includes(state.status) && <div className={remaining < 300 ? 'clock urgent' : 'clock'}>剩余时间 {clock}</div>}</header>
    <main className="candidate-main">{fatal ? <Alert type="error" showIcon message="链接无法使用" description={fatal} /> : !state ? <div className="center"><Spin /></div> : <>
      <div className="candidate-title"><Typography.Text type="secondary">{state.job_name}</Typography.Text><Typography.Title level={2}>{state.candidate_name}，你好</Typography.Title></div>
      {['exam_in_progress', 'interview_in_progress', 'practical_in_progress'].includes(state.status) && <Steps className="block"
        current={state.status === 'exam_in_progress' ? 0 : state.status === 'interview_in_progress' ? 1 : 2}
        items={[{ title: '计时笔试' }, { title: 'AI 三轮问答' }, { title: 'AI 编程实操' }, { title: '完成' }]} />}
      {objectiveFeedback && <Card className="block">{bulbs}<Alert type={objectiveFeedback.correct ? 'success' : 'error'} showIcon
        message={objectiveFeedback.correct ? '回答正确' : '回答错误'}
        description={objectiveFeedback.nextDifficulty ? `下一题实际难度：${objectiveFeedback.nextDifficulty}` : '五道客观题已完成。'} />
        <div className="exam-actions"><span className="muted">答案已锁定，不能修改。</span><Button type="primary" onClick={() => setObjectiveFeedback(undefined)}>
          {objectiveFeedback.nextDifficulty ? '继续下一题' : '进入 AI 问答'}</Button></div></Card>}
      {!objectiveFeedback && state.status === 'exam_in_progress' && exam?.adaptive && <Card className="block">{bulbs}
        {adaptiveQuestion ? <><div className="question-top"><span>题目 {adaptiveQuestion.order_no} / {exam.total}</span>
          <span>难度 {adaptiveQuestion.difficulty} / 5</span></div>
          <Typography.Title level={4} className="question-content">{adaptiveQuestion.content}</Typography.Title>
          <Radio.Group value={value} onChange={e => setValue(e.target.value)} className="choice-list">
            {(adaptiveQuestion.options || []).map((option: string) => <Radio key={option} value={option}>{option}</Radio>)}
          </Radio.Group>
          <div className="exam-actions"><span className="muted">提交后立即显示对错，不能返回修改。</span>
            <Button type="primary" disabled={!value} loading={busy} onClick={submitObjective}>提交本题</Button></div></> : <Spin />}
      </Card>}
      {!objectiveFeedback && state.status === 'exam_in_progress' && !exam?.adaptive && <>{q ? <Card className="block">
        <div className="question-top"><span>题目 {index + 1} / {exam.questions.length}</span><span>难度 {q.difficulty} / 5 · {q.score_points} 分</span></div>
        <Progress percent={Math.round((index + 1) / exam.questions.length * 100)} showInfo={false} strokeColor="#275d5b" />
        <Typography.Title level={4} className="question-content">{q.content}</Typography.Title>
        {q.type === 'SINGLE_CHOICE' ? <Radio.Group value={value} onChange={e => change(e.target.value)} className="choice-list">
          {(q.options || []).map((option: string) => <Radio key={option} value={option}>{option}</Radio>)}</Radio.Group>
          : q.type === 'MULTIPLE_CHOICE' ? <Checkbox.Group value={value} onChange={change} className="choice-list">
            {(q.options || []).map((option: string) => <Checkbox key={option} value={option}>{option}</Checkbox>)}</Checkbox.Group>
            : <Input.TextArea rows={8} value={value} onChange={e => change(e.target.value)} placeholder="请输入你的回答。切题时会自动保存。" />}
        <div className="exam-actions"><Space><Button disabled={index === 0} onClick={() => move(index - 1)}>上一题</Button>
          <Button disabled={index === exam.questions.length - 1} onClick={() => move(index + 1)}>下一题</Button></Space>
          <Button type="primary" loading={busy} onClick={submitExam}>提交笔试</Button></div>
      </Card> : <Spin />}</>}
      {!objectiveFeedback && state.status === 'interview_in_progress' && <Card className="block">
        {state.ai_failure ? <Alert type="error" showIcon message="AI 问答暂时无法继续" description="请点击下方按钮终止本次计时，并联系 HR 处理。" />
          : state.current_turn ? <><Tag color="blue">第 {state.current_turn.round_no} / 3 轮</Tag>
            <Typography.Title level={4} className="question-content">{state.current_turn.question}</Typography.Title>
            <Input.TextArea rows={7} value={reply} onChange={e => setReply(e.target.value)} placeholder="请结合自己的实际经历回答" />
            <div className="exam-actions"><span className="muted">提交后不可修改</span><Button type="primary" disabled={!reply.trim()} loading={busy} onClick={submitReply}>提交回答</Button></div></>
            : <div className="center"><Spin /><p>正在生成下一轮问题，请稍候…</p></div>}
        {state.ai_failure && <Button danger className="top-gap" loading={busy} onClick={suspend}>终止计时并联系 HR</Button>}
      </Card>}
      {state.status === 'practical_in_progress' && <Card className="block" title="AI Agent 执行轨迹诊断实操">
        <Alert type="info" showIcon message="请在本地使用 AI 编程工具完成"
          description="数据包因人而异，包含乱序、重试、重复修正和依赖图。只需 Python 3.11 标准库；服务端不会执行你的代码。" />
        <div className="top-gap"><Space wrap>
          <a href={'/api' + base + '/practical/package'} download><Button type="primary">下载专属题目包</Button></a>
          <Tag>最多提交 {practical?.attempt_limit || 5} 次</Tag>
          <Tag color="blue">已提交 {practical?.attempt_count || 0} 次</Tag>
          <Tag color="green">最高 {practical?.best_score || 0} 分</Tag>
        </Space></div>
        {!!practical?.breakdown && Object.keys(practical.breakdown).length > 0 && <div className="top-gap">
          {Object.entries(practical.breakdown).map(([key, value]) => <Tag key={key}>{key}: {String(value)}</Tag>)}
        </div>}
        {!!practical?.feedback?.length && <Alert className="top-gap" type="warning" showIcon message="未通过分项"
          description={practical.feedback.join('；')} />}
        <Typography.Paragraph className="top-gap" type="secondary">
          解压后阅读 README，完成 solution/solve.py、output/report.json 和 AI_WORKLOG.md，再把整个目录压缩为 ZIP 上传。
        </Typography.Paragraph>
        <Upload beforeUpload={() => false} maxCount={1} accept=".zip" fileList={packageFile}
          onChange={({ fileList }) => setPackageFile(fileList)}><Button>选择 ZIP 提交包</Button></Upload>
        <div className="exam-actions"><span className="muted">可根据分项反馈迭代；确认后不能再提交。</span><Space>
          <Button type="primary" disabled={!packageFile[0]} loading={busy} onClick={submitPractical}>上传并验收</Button>
          <Button disabled={!practical?.can_finalize} loading={busy} onClick={finalizePractical}>确认最高分并结束</Button>
        </Space></div>
      </Card>}
      {state.status === 'suspended' && <Alert type="warning" showIcon message="测评已挂起" description="计时已暂停。请联系 HR；待 HR 修复并恢复后，刷新此页面继续作答。" />}
      {state.status === 'scoring' && <Card><div className="center"><Spin size="large" /><Typography.Title level={4}>答案已提交，正在整理测评</Typography.Title><p>请稍候。你可以关闭页面。</p></div></Card>}
      {state.status === 'completed' && <Card><div className="center"><Typography.Title level={3}>测评已经完成</Typography.Title><p>感谢你的参与。</p></div></Card>}
      {state.status === 'expired' && <Alert type="warning" message="链接已过期" description="请联系 HR 重新生成链接。" />}
      {state.status === 'cancelled' && <Alert type="info" message="本次测评已取消" />}
    </>}</main></div>;
}
