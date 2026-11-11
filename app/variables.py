"""A finite typed variable catalog, never an expression evaluator."""
import math
import re
from .domain import require,parse_date

CATALOG={'focus':'string','question':'string','metrics.completion_rate':'number','context.has_evidence':'boolean','period_end':'date','context.mode':'enum','context.metrics_summary':'object','evidence':'array','context.snapshot_ref':'reference'}
RESERVED={'tenant_id','actor_id','project_id','authorized_scope','permissions','credentials','tools','metrics','configuration'}


def defaults(scene='PROGRESS'):
    target='AnalyzeAgent' if scene=='PROGRESS' else 'GenerateAnswer'
    sources=['focus','metrics.completion_rate','context.has_evidence','period_end','context.mode','context.metrics_summary','evidence','context.snapshot_ref'] if scene=='PROGRESS' else ['question','context.has_evidence','context.mode','evidence']
    return [{'name':source.replace('context.','').replace('metrics.','').replace('.','_'),'type':CATALOG[source],'required':True,'default':None,'enum':['DEMO_RULES'] if CATALOG[source]=='enum' else [],'min':None,'max':100 if source=='metrics.completion_rate' else None,'max_length':40000,'source':source,'allowed_nodes':[target],'empty_policy':'ALLOW' if source in {'metrics.completion_rate','focus'} else 'ERROR'} for source in sources]


def value_valid(spec,value):
    if value is None:
        require(spec['empty_policy']=='ALLOW' or not spec['required'],'变量 '+spec['name']+' 缺少必填值','VARIABLE_MISSING',409);return
    kind=spec['type'];valid=False
    if kind=='string':valid=isinstance(value,str)
    elif kind=='number':valid=type(value) in {int,float} and math.isfinite(value)
    elif kind=='boolean':valid=type(value) is bool
    elif kind=='date':
        valid=isinstance(value,str)
        if valid:parse_date(value)
    elif kind=='enum':valid=isinstance(value,str) and value in spec['enum']
    elif kind=='object':valid=isinstance(value,dict)
    elif kind=='array':valid=isinstance(value,list)
    elif kind=='reference':valid=isinstance(value,dict) and set(value)=={'object_type','id'} and value['object_type']=='snapshot' and isinstance(value['id'],str)
    require(valid,'变量 '+spec['name']+' 类型不匹配，节点已停止','VARIABLE_TYPE_MISMATCH',409)
    if kind=='number':
        require((spec['min'] is None or value>=spec['min']) and (spec['max'] is None or value<=spec['max']),'变量 '+spec['name']+' 超出数值范围','VARIABLE_RANGE',409)
    if isinstance(value,(str,list)):require(len(value)<=spec['max_length'],'变量 '+spec['name']+' 超过长度限制','VARIABLE_RANGE',409)


def validate(specs,scene):
    require(isinstance(specs,list) and len(specs)<=24,'变量定义最多 24 项')
    names=set();target='AnalyzeAgent' if scene=='PROGRESS' else 'GenerateAnswer'
    fields={'name','type','required','default','enum','min','max','max_length','source','allowed_nodes','empty_policy'}
    for s in specs:
        require(isinstance(s,dict) and set(s)==fields,'变量字段不完整或包含未知字段')
        name=s['name'];require(isinstance(name,str) and re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,39}',name) and name not in names and name not in RESERVED,'变量名称重复、无效或为系统保留字段');names.add(name)
        require(s['source'] in CATALOG and (scene=='PROGRESS' or s['source'] in {'question','evidence','context.has_evidence','context.mode'}),'来源不在必经节点的合法字段目录中')
        require(s['type']==CATALOG[s['source']],'变量类型与来源路径不匹配')
        require(type(s['required']) is bool and s['empty_policy'] in {'ERROR','ALLOW'},'必须明确必填与空值策略')
        require(s['allowed_nodes']==[target],'变量只能传入当前场景的分析节点，不能覆盖业务状态')
        require(type(s['max_length']) is int and 1<=s['max_length']<=40000,'变量长度上限为 1～40000')
        for field in ['min','max']:require(s[field] is None or type(s[field]) in {int,float} and math.isfinite(s[field]),'变量范围无效')
        require(s['min'] is None or s['max'] is None or s['min']<=s['max'],'变量最小值大于最大值')
        require(isinstance(s['enum'],list) and len(s['enum'])<=50 and all(isinstance(x,str) for x in s['enum']) and (s['type']!='enum' or s['enum']),'枚举选项无效')
        if s['default'] is not None:value_valid(s,s['default'])


def resolve(configuration,data,node,question=None,snapshot_id=None):
    scene=configuration.get('scene','PROGRESS');specs=configuration.get('variables',defaults(scene));validate(specs,scene)
    metrics=data.get('metrics',{});source={'focus':data.get('focus',''),'question':question or '','metrics.completion_rate':metrics.get('completion_rate'),'context.has_evidence':bool(data.get('evidence')),'period_end':data.get('period_end'),'context.mode':'DEMO_RULES','context.metrics_summary':{k:v for k,v in metrics.items() if k in {'total','completed','overdue_count'}},'evidence':data.get('evidence',[]),'context.snapshot_ref':{'object_type':'snapshot','id':snapshot_id or data.get('snapshot_id','')}}
    result={}
    for s in specs:
        if node not in s['allowed_nodes']:continue
        value=source[s['source']]
        if value is None and s['default'] is not None:value=s['default']
        value_valid(s,value);result[s['name']]=value
    return result
