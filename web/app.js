if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js').catch(()=>{});

document.getElementById('start').addEventListener('click',()=>{
  const specialty=document.getElementById('specialty').value;
  const questionType=document.getElementById('questionType').value;

  const specialtyLabel = specialty === 'ALL' ? 'all medical specialties' : specialty;
  const questionLabel = questionType === 'ALL' ? 'all review-question types' : questionType.replaceAll('_', ' ').toLowerCase();

  alert(`Review-topic discovery is ready for ${specialtyLabel} across ${questionLabel}. Connect the backend to run the discovery workflow.`);
});
