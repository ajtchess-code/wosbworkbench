"""Read managed metadata and a restricted subset of IL; never load/execute game DLLs."""
import math, struct
import dnfile
from dncil.cil.body.reader import read_method_body_from_bytes
from dncil.clr.token import Token, StringToken

class Unknown:
    def __repr__(self): return 'UNRESOLVED'
U=Unknown()
def plain(v):
    if isinstance(v,Unknown): return None
    if isinstance(v,list): return [plain(x) for x in v]
    if isinstance(v,dict): return {str(k):plain(x) for k,x in v.items()}
    return v

def cint(b,pos=0):
    a=b[pos];pos+=1
    if a<128:return a,pos
    if a<192:return ((a&63)<<8)|b[pos],pos+1
    return ((a&31)<<24)|(b[pos]<<16)|(b[pos+1]<<8)|b[pos+2],pos+3

class Metadata:
    def __init__(self,path, prepare_strings=True):
        self.pe=dnfile.dnPE(str(path));self.path=str(path);self.owners={};self.strings={};self.bodies={}
        for t in self.pe.net.mdtables.TypeDef.rows:
            for x in list(t.MethodList)+list(t.FieldList):self.owners[id(x.row)]=str(t.TypeNamespace)+'.'+str(t.TypeName)
        if not prepare_strings:
            return
        for t in self.pe.net.mdtables.TypeDef.rows:
            if not str(t.TypeNamespace).startswith('<PrivateImplementationDetails>'):continue
            try:
                init=next(m for m in t.MethodList if str(m.row.Name)=='.cctor')
                ii=self.body(init.row_index)
                field=next(i.operand.rid for i in ii if i.opcode.name=='ldtoken')
                size=[i.operand for i in ii if i.opcode.name=='ldc.i4'][1]
                rva=next(r.Rva for r in self.pe.net.mdtables.FieldRva.rows if r.Field.row_index==field)
                buf=bytes((v^j^170)&255 for j,v in enumerate(self.pe.get_data(rva,size)))
                for m in t.MethodList:
                    constants=[self.const(i) for i in self.body(m.row_index) if i.opcode.name.startswith('ldc.i4')]
                    if len(constants)==4:
                        self.strings[0x06000000+m.row_index]=buf[constants[-2]:constants[-2]+constants[-1]].decode('utf-8')
            except (StopIteration,IndexError,ValueError,AttributeError):continue
    @staticmethod
    def const(i):
        n=i.opcode.name
        return i.operand if n in ('ldc.i4','ldc.i4.s','ldc.i8','ldc.r4','ldc.r8') else (-1 if n.endswith('m1') else int(n[-1]))
    def body(self,rid):
        if rid not in self.bodies:
            r=self.pe.net.mdtables.MethodDef.rows[rid-1]
            if not r.Rva:raise ValueError('Method has no IL')
            # Read to end of the containing PE section so large methods are not truncated.
            self.bodies[rid]=read_method_body_from_bytes(self.pe.get_data(r.Rva)).instructions
        return self.bodies[rid]
    def body_limited(self, rid, max_il_bytes=262144):
        """Decode only a bounded method body, without retaining it in self.bodies.

        Only static IL bytecode is parsed; no game assemblies are loaded/executed.
        A method exceeding the byte budget is skipped and reported to the caller.
        """
        row = self.pe.net.mdtables.MethodDef.rows[rid - 1]
        if not row.Rva:
            raise ValueError('Method has no IL')
        header = self.pe.get_data(row.Rva, 12)
        if not header:
            raise ValueError('Missing method header')
        header_type = header[0] & 3
        if header_type == 2:  # tiny header
            needed = 1 + (header[0] >> 2)
        elif header_type == 3:  # fat header
            if len(header) < 12:
                raise ValueError('Truncated fat method header')
            header_word = struct.unpack_from('<H', header)[0]
            header_bytes = ((header_word >> 12) & 0x0f) * 4
            code_bytes = struct.unpack_from('<I', header, 4)[0]
            if header_bytes < 12:
                raise ValueError('Invalid fat method header')
            needed = header_bytes + code_bytes
            # Allow bounded room for EH/extra sections, if present.
            if header_word & 8:
                needed += min(8192, max_il_bytes // 8)
        else:
            raise ValueError('Unsupported .NET method header')
        if needed > max_il_bytes:
            raise ValueError('Method exceeds IL byte limit')
        data = self.pe.get_data(row.Rva, needed)
        return read_method_body_from_bytes(data).instructions

    def row(self,tok):return self.pe.net.mdtables.tables[tok.table].rows[tok.rid-1]
    def typename(self,row):
        if hasattr(row,'TypeName'):return str(row.TypeNamespace)+'.'+str(row.TypeName)
        if hasattr(row,'Signature'):
            b=row.Signature.value
            if b[:2] in (b'\x15\x11',b'\x15\x12'):
                token,_=cint(b,2);table=[2,1,27][token&3];return self.typename(self.pe.net.mdtables.tables[table].rows[(token>>2)-1])
        return '?'
    def method(self,tok):
        if tok.table==43:
            x=self.row(tok).Method
            return self.method(Token((6 if x.table.name=='MethodDef' else 10)<<24 | x.row_index))
        r=self.row(tok);owner=self.owners.get(id(r))
        if owner is None:owner=self.typename(r.Class.row)
        return owner,str(r.Name),r
    def sig(self,row):
        b=row.Signature.value;p=1
        if b[0]&16:_,p=cint(b,p)
        count,p=cint(b,p)
        return count,bool(b[0]&32),b[p]!=1
    def find(self,owner,name):
        for idx,m in enumerate(self.pe.net.mdtables.MethodDef.rows,1):
            if self.owners.get(id(m))==owner and str(m.Name)==name:return idx
        raise ValueError('Missing method '+owner+'::'+name)
    def evidence(self,rid):
        lines=[]
        for i in self.body(rid):
            a=i.operand
            if isinstance(a,StringToken):a=repr(self.pe.net.user_strings.get(a.rid).value)
            elif isinstance(a,Token):
                if a.value in self.strings:a=repr(self.strings[a.value])
                elif a.table in (6,10,43):
                    o,n,_=self.method(a);a=o+'::'+n+' '+str(a)
                else:
                    r=self.row(a);a=self.owners.get(id(r),'')+'::'+str(getattr(r,'Name',getattr(r,'TypeName',a)))+' '+str(a)
            lines.append(f'{i.offset:04x} {i.opcode.name} {a if a is not None else ""}')
        return '\n'.join(lines)
    def archive_password(self):
        rid=self.find('TheraEngine.Core.HeapLoader','OpenStream');ii=self.body(rid)
        for j,i in enumerate(ii):
            if i.opcode.name=='callvirt' and self.method(i.operand)[1]=='set_Password':
                prev=ii[j-1].operand
                if prev.value in self.strings:return self.strings[prev.value].encode()
        raise ValueError('Archive key cannot be resolved for this build')

class StaticVM:
    """Allowlisted data constructors and arithmetic, not a general .NET runtime."""
    def __init__(self,meta):self.m=meta;self.fields={};self.created=[];self.depth=0
    def run(self,rid,args=()):
        if self.depth>20:raise ValueError('IL recursion limit')
        self.depth+=1
        try:return self._run(rid,list(args))
        finally:self.depth-=1
    def invoke(self,tok,args,construct=False):
        if tok.value in self.m.strings:return self.m.strings[tok.value]
        owner,name,row=self.m.method(tok)
        if owner=='System.Runtime.CompilerServices.RuntimeHelpers' and name=='InitializeArray':
            dest,token=args
            rva=next(r.Rva for r in self.m.pe.net.mdtables.FieldRva.rows if r.Field.row_index==token.rid)
            dest[:]=struct.unpack('<'+'i'*len(dest),self.m.pe.get_data(rva,len(dest)*4))
            return None
        if name in ('op_Implicit','op_Explicit','get_Value','GetValueOrDefault'):return args[-1]
        if owner=='Common.Game.GSI':
            if name=='.ctor':return {'_type':'GSI','items':{}}
            d=args[0]['items']
            if name in ('Exs','set_Item'):
                d[args[1]]=args[2];return args[0] if name=='Exs' else None
            if name=='get_Item':return d.get(args[1],0)
            if name=='get_IsEmpty':return not any(d.values())
        if name=='.ctor':
            if owner.endswith('.Recepie'):
                if len(args)==5:
                    h,cat,ins,outs,gold=args
                    obj={'_type':'Recipe','CraftHours':h,'CategoryKey':cat,'InputItems':ins['items'],'OutputItems':outs['items'],'InputGold':gold}
                elif len(args) in (6,7):
                    if len(args)==7:h,cat,gold,inid,qty,outid,outqty=args
                    else:h,cat,inid,qty,outid,outqty=args;gold=0
                    inputs=dict(zip(inid,qty)) if isinstance(inid,list) else {inid:qty}
                    obj={'_type':'Recipe','CraftHours':h,'CategoryKey':cat,'InputGold':gold,'InputItems':inputs,'OutputItems':{outid:outqty}}
                else:raise ValueError('Unknown recipe constructor')
                self.created.append(obj);return obj
            if owner=='System.Nullable`1' or owner.startswith('TheraEngine.RTI'):return args[0] if args else None
            return {'_type':owner,'args':args}
        if owner in ('System.Math','System.MathF'):
            if any(isinstance(x,Unknown) for x in args):return U
            f={'Max':max,'Min':min,'Round':round,'Floor':math.floor,'Ceiling':math.ceil,'Pow':pow,'Abs':abs,'Sqrt':math.sqrt}.get(name)
            if f:return f(*args)
        # Only known arithmetic helpers may be recursively interpreted.
        if tok.table==6 and tok.rid in self.allowed:
            if tok.rid==0x2303 and any(isinstance(x,Unknown) for x in args):return U
            return self.run(tok.rid,args)
        if owner=='System.Linq.Enumerable':
            if name in ('ToArray','ToList'):return args[0]
            if name=='Concat':return list(args[0])+list(args[1])
            delegate=args[1] if len(args)>1 else None
            target=delegate.get('args',[None,None])[-1] if isinstance(delegate,dict) else None
            if name=='Where' and target=='token(0x0600237E)':
                return [r for r in args[0] if r.get('NeedsFactoryInPort') is not None and r.get(0x04000d0b,0)==0]
            if name=='Select' and target=='token(0x0600237F)':
                result=[]
                for r in args[0]:
                    new={'_type':'Recipe','CraftHours':r['CraftHours']/20,'CategoryKey':'','InputGold':0,'InputItems':dict(r['InputItems']),'OutputItems':dict(r['OutputItems']),'NeedsFactoryInPort':r.get('NeedsFactoryInPort'),'Context':'Personal island workshop'}
                    self.created.append(new);result.append(new)
                return result
        raise ValueError('Unsupported IL call '+owner+'::'+name)
    allowed=set()
    def _run(self,rid,args):
        ii=self.m.body(rid);positions={i.offset:j for j,i in enumerate(ii)};s=[];loc={};pc=0;steps=0
        while pc<len(ii):
            i=ii[pc];pc+=1;steps+=1;n=i.opcode.name;a=i.operand
            if steps>200000:raise ValueError('IL instruction limit')
            def idx(prefix):return a.index if n in (prefix,prefix+'.s',prefix+'a',prefix+'a.s') else int(n[-1])
            if n.startswith('ldc.'):s.append(self.m.const(i))
            elif n=='ldnull':s.append(None)
            elif n=='ldstr':s.append(self.m.pe.net.user_strings.get(a.rid).value)
            elif n.startswith('ldarg'):s.append(args[idx('ldarg')])
            elif n.startswith('ldloc'):s.append(loc.get(idx('ldloc'),0))
            elif n.startswith('stloc'):loc[idx('stloc')]=s.pop()
            elif n.startswith('starg'):args[a.index]=s.pop()
            elif n=='dup':s.append(s[-1])
            elif n=='pop':s.pop()
            elif n=='ldtoken':s.append(a)
            elif n=='ldftn':s.append(str(a))
            elif n=='newarr':s.append([0]*s.pop())
            elif n.startswith('stelem'):
                v=s.pop();index=s.pop();s.pop()[index]=v
            elif n.startswith('ldelem'):
                index=s.pop();s.append(s.pop()[index])
            elif n=='ldlen':s.append(len(s.pop()))
            elif n in ('ldsfld','ldsflda'):s.append(self.fields.get(a.value,U))
            elif n=='stsfld':self.fields[a.value]=s.pop()
            elif n in ('ldfld','ldflda'):
                v=s.pop();key=str(self.m.row(a).Name)
                s.append(v.get(a.value,v.get(key,U)) if isinstance(v,dict) else U)
            elif n=='stfld':
                v=s.pop();obj=s.pop();obj[a.value]=v;obj[str(self.m.row(a).Name)]=v
            elif n in ('call','callvirt','newobj'):
                owner,name,row=self.m.method(a);count,hasthis,returns=self.m.sig(row)
                if n!='newobj' and hasthis:count+=1
                vals=s[-count:] if count else []
                if count:del s[-count:]
                v=self.invoke(a,vals,n=='newobj')
                if returns or n=='newobj':s.append(v)
            elif n.startswith('conv.'):
                v=s.pop()
                s.append(U if isinstance(v,Unknown) else (int(v) if n.startswith('conv.i') or n.startswith('conv.u') else float(v)))
            elif n in ('add','sub','mul','div','div.un','rem','rem.un','and','or','xor','shl','shr'):
                y=s.pop();x=s.pop()
                if isinstance(x,Unknown) or isinstance(y,Unknown):s.append(U)
                else:s.append({'add':lambda:x+y,'sub':lambda:x-y,'mul':lambda:x*y,'div':lambda:x/y,'div.un':lambda:x//y,'rem':lambda:x%y,'rem.un':lambda:x%y,'and':lambda:x&y,'or':lambda:x|y,'xor':lambda:x^y,'shl':lambda:x<<y,'shr':lambda:x>>y}[n]())
            elif n in ('ceq','cgt','cgt.un','clt','clt.un'):
                y=s.pop();x=s.pop()
                if isinstance(x,Unknown) or isinstance(y,Unknown):s.append(U)
                else:s.append(int(x==y if n=='ceq' else (x>y if n.startswith('cgt') else x<y)))
            elif n in ('br','br.s','leave','leave.s'):pc=positions[a]
            elif n.startswith(('brtrue','brfalse')):
                v=s.pop()
                if isinstance(v,Unknown):raise ValueError('Unknown IL branch condition')
                if bool(v)==n.startswith('brtrue'):pc=positions[a]
            elif n.startswith(('beq','bne','bge','bgt','ble','blt')):
                y=s.pop();x=s.pop()
                if isinstance(x,Unknown) or isinstance(y,Unknown):raise ValueError('Unknown IL branch comparison')
                op=n.split('.')[0]
                ok={'beq':lambda:x==y,'bne':lambda:x!=y,'bge':lambda:x>=y,'bgt':lambda:x>y,'ble':lambda:x<=y,'blt':lambda:x<y}[op]()
                if '.un' in n and (x<0 or y<0):
                    x=int(x)&0xffffffff;y=int(y)&0xffffffff
                    ok={'bne':lambda:x!=y,'bgt':lambda:x>y,'bge':lambda:x>=y,'blt':lambda:x<y,'ble':lambda:x<=y}.get(op,lambda:x==y)()
                if ok:pc=positions[a]
            elif n=='switch':
                v=s.pop()
                if 0<=v<len(a):pc=positions[a[v]]
            elif n in ('box','unbox.any','castclass','nop','constrained.'):pass
            elif n=='ret':return s.pop() if s else None
            else:raise ValueError('Unsupported IL opcode '+n)
        return None
