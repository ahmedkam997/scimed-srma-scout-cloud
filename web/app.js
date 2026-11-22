if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js').catch(()=>{});
document.getElementById('start').addEventListener('click',()=>{
  const specialty=document.getElementById('specialty').value;
  alert(`Review-topic discovery is ready for ${specialty}. Connect the backend to run the discovery workflow.`);
});
