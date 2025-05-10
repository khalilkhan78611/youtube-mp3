async function pollStatus(downloadId) {
    try {
        const response = await fetch(`/check_status/${downloadId}`);
        const data = await response.json();

        if (data.status === 'completed') {
            // Handle successful download
        } 
        else if (data.status === 'error') {
            let errorMessage = data.message;
            
            // Special handling for YouTube errors
            if (data.message.includes('blocking this download')) {
                errorMessage += '<br><br>Try these solutions:';
                errorMessage += '<br>1. Wait a few minutes and try again';
                errorMessage += '<br>2. Try a different video';
                errorMessage += '<br>3. The video may have restrictions';
            }
            
            statusDiv.innerHTML = `<span style="color:red">Error: ${errorMessage}</span>`;
            cancelBtn.style.display = 'none';
        }
        else {
            // Continue polling
            setTimeout(() => pollStatus(downloadId), 1000);
        }
    } catch (error) {
        statusDiv.innerHTML = '<span style="color:red">Connection error checking status</span>';
        console.error('Error:', error);
    }
}
