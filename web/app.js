const $ = (id) => document.getElementById(id);
const fmt = (v) => v == null ? '未知' : new Intl.NumberFormat('zh-CN', {maximumFractionDigits:2}).format(v);
const el = (tag, text, cls) => {const node=document.createElement(tag); if(text!=null) node.textContent=text; if(cls)node.className=cls;return node;};
const kinds={cash:'现金',security:'证券',pending:'在途',liability:'负债'};
async function refresh(){
  try{
    const response=await fetch('/api/snapshot');
    if(!response.ok)throw new Error('账本校验失败，请在终端运行 validate');
    const s=await response.json();
    $('status').textContent=`${s.mode==='demo'?'演示模式 · 所有账户、金额和价格均为虚构，不能用作市场数据。':'个人模式 · 数据仅通过本机服务展示。'} ${s.gaps.length} 项估值缺口 · ${s.stale_sources.length} 条价格/汇率超过七天 · ${s.pending_events} 条待确认记录`;
    $('metrics').replaceChildren();
    for(const [label,value,note] of [['净资产',s.net_worth,`资产 ${fmt(s.total_assets)} − 负债 ${fmt(s.total_liabilities)}`],['月度结余',s.cashflow.monthly_surplus,'基于用户填写的月收入与支出'],['应急储备',s.emergency.available,`目标 ${fmt(s.emergency.target)} · 覆盖 ${fmt(s.emergency.months_covered)} 个月`],['目标月投入',s.plan.goals_monthly_required,`投入后月结余 ${fmt(s.plan.goal_surplus_after_contributions)}`]]){
      const card=el('article',null,'metric');card.append(el('div',label,'metric-label'),el('div',fmt(value),'metric-value'),el('div',note,'metric-note'));$('metrics').append(card);
    }
    $('allocation').replaceChildren();
    for(const a of s.plan.allocation){
      const row=el('div',null,'allocation-row'), middle=el('div'), labels=el('div',null,'bar-label'), bar=el('progress');
      labels.append(el('span',`${fmt(a.actual_percent)}%`),el('span',`目标 ${fmt(a.target_percent)}%`));bar.max=100;bar.value=a.actual_percent||0;bar.setAttribute('aria-label',`${a.category} 实际占比`);middle.append(labels,bar);row.append(el('span',a.category),middle,el('span',`差额 ${fmt(a.gap)}`,'gap'));$('allocation').append(row);
    }
    if(!s.plan.allocation.length)$('allocation').textContent='尚未设置资产与目标配置。';
    $('goals').replaceChildren();$('plan-status').textContent=s.plan.status==='draft'?'草案 · 待确认':'已确认计划 · 不等于执行';
    for(const g of s.plan.goals){const node=el('div',null,'goal'),title=el('div',null,'goal-title');title.append(el('span',g.name),el('strong',`${fmt(g.monthly_required)} / 月`));node.append(title,el('p',`已专项预留 ${fmt(g.saved_amount)} / 目标 ${fmt(g.target_amount)} · 剩余 ${g.months} 个月`));$('goals').append(node);}
    $('goal-summary').textContent='目标已存金额是已有资产的用途标记，不会再次计入总资产；多个目标应分别预留，避免重复使用同一笔钱。';
    $('currency').textContent=`统一折算为 ${s.base_currency}`;$('positions').replaceChildren();
    for(const p of s.positions){const row=el('tr'),name=el('td',p.name),source=el('td',p.price_as_of?.slice(0,10)||'缺少日期');name.append(el('small',`${p.account} · ${kinds[p.kind]}`));source.append(el('small',p.price_source||'缺少来源'));row.append(name,el('td',fmt(p.quantity)),el('td',fmt(p.value)),source);$('positions').append(row);}
    $('checks').replaceChildren();
    for(const item of [...s.gaps,...s.stale_sources,`已应用 ${s.confirmed_events} 条确认事件；未确认记录 ${s.pending_events} 条。`])$('checks').append(el('li',item));
    $('footer').textContent=`Wealth OS Starter · 本地决策辅助，无交易接口。生成时间 ${s.as_of} · 版本 ${s.revision}`;
  }catch(error){$('status').textContent=error.message;for(const id of ['metrics','allocation','positions','goals','checks','footer'])$(id).replaceChildren();}
}
$('refresh').addEventListener('click',refresh);
// Independent scenario only. Portfolio, allocation and cashflow are never recomputed in the browser.
$('scenario').addEventListener('submit',(event)=>{
  event.preventDefault();const form=new FormData(event.target);const initial=Number(form.get('initial')),monthly=Number(form.get('monthly')),rate=Number(form.get('rate')),years=Number(form.get('years'));
  if(![initial,monthly,rate,years].every(Number.isFinite)||initial<0||monthly<0||rate<=-100||rate>100||!Number.isInteger(years)||years<1||years>80)return;
  let balance=initial;for(let m=0;m<years*12;m++)balance=balance*(1+rate/1200)+monthly;
  $('scenario-result').textContent=`假设 ${years} 年后：${fmt(balance)}；累计本金：${fmt(initial+monthly*years*12)}。这是输入假设的计算结果，不是收益承诺。`;
});
refresh();
