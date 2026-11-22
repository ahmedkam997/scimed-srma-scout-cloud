if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js').catch(()=>{});
document.getElementById('start').addEventListener('click',()=>{
  const specialty=document.getElementById('specialty').value;
  alert(`Prototype ready for ${specialty}. Backend connection is the next milestone.`);
});
