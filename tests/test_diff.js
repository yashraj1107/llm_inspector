function computeWordDiff(str1, str2) {
  if (typeof str1 !== 'string') str1 = '';
  if (typeof str2 !== 'string') str2 = '';
  const words1 = str1.trim() ? str1.trim().split(/\s+/) : [];
  const words2 = str2.trim() ? str2.trim().split(/\s+/) : [];
  
  const n = words1.length;
  const m = words2.length;
  const dp = Array(n + 1).fill(null).map(() => Array(m + 1).fill(0));
  
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      if (words1[i - 1] === words2[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }
  
  const segments = [];
  let i = n, j = m;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && words1[i - 1] === words2[j - 1]) {
      segments.unshift({ type: 'same', value: words1[i - 1] });
      i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      segments.unshift({ type: 'added', value: words2[j - 1] });
      j--;
    } else {
      segments.unshift({ type: 'removed', value: words1[i - 1] });
      i--;
    }
  }
  return segments;
}

const origText = "What is the capital of France?";
const newText = "What is the capital of Germany?";

console.log(JSON.stringify(computeWordDiff(origText, newText), null, 2));
