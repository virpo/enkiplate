(async () => {
  const {openStorage, saveState, loadState} = await import('/web/storage.js');
  const name = 'enki-regression-' + crypto.getRandomValues(new Uint32Array(1))[0];
  let a, b, c;
  const check=(condition,message)=>{if(!condition)throw Error(message)};
  const base={cards:[],index:0,side:'front',pending:[]};
  try {
    a=await openStorage(name);b=await openStorage(name);
    await saveState(a,{...base,index:1},{event:{id:'A',rating:3}});
    await saveState(b,{...base,side:'back'});
    check((await loadState(b)).pending[0].id==='A','A stale tab erased the other tab’s answer');
    await saveState(b,{...base,index:1},{event:{id:'B',rating:1}});
    await saveState(a,{...base,index:1},{ack:['A']});
    a.close();a=null;b.close();b=null;
    c=await openStorage(name);
    const restored=await loadState(c);
    check(restored.pending.length===1&&restored.pending[0].id==='B','Acknowledgement erased an unacknowledged answer');
    return {two_connections:true,stale_reveal_preserved_answer:true,ack_preserved_other_answer:true,reopen_preserved_answer:true};
  } finally {
    a?.close();b?.close();c?.close();
    indexedDB.deleteDatabase(name);
  }
})()
