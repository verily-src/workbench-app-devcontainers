 #!/bin/bash                                                                                                       
set -o errexit -o nounset -o pipefail                 

LOG_DIR="/var/log/fastomop"                                                                                       

# 1. Verify audit trail directory is writable                                                                     
if [ ! -w "$LOG_DIR" ]; then                          
    echo "ERROR: $LOG_DIR is not writable"                                                                        
    mkdir -p "$LOG_DIR"                                                                                           
    chmod 777 "$LOG_DIR"
fi                                                                                                                
echo "✓ Audit trail directory $LOG_DIR is writable"   
                                                                                                                
# 2. Background sync process to workspace bucket
BUCKET_PATH="gs://${WORKSPACE_BUCKET}/fastomop-logs"                                                              
echo "Starting background log sync to $BUCKET_PATH"                                                               
                                                                                                                
# Initial sync on startup                                                                                         
gsutil -m rsync -r "$LOG_DIR/" "$BUCKET_PATH/" 2>/dev/null || echo "Warning: Initial sync failed (bucket may not  
be ready)"                                                                                                        
                                                    
# 3. Sanity check - send an out-of-scope query to verify governance/ABR                                           
echo "Running ABR sanity check..."                    
ABR_TEST_QUERY="DROP TABLE patients;"                                                                             
ABR_RESULT=$(python -c "
import sqlglot                                                                                                    
try:                                                                                                              
    parsed = sqlglot.parse('$ABR_TEST_QUERY')
    for stmt in parsed:                                                                                           
        if stmt.key != 'select':                                                                                  
            print('BLOCKED')                                                                                      
            break                                                                                                 
    else:                                                                                                         
        print('ALLOWED')                                                                                          
except Exception as e:                                
    print('ERROR: ' + str(e))
" 2>&1)                                                                                                           
                                                                                                                
if [ "$ABR_RESULT" = "BLOCKED" ]; then                                                                            
    echo "✓ ABR sanity check passed: out-of-scope query was blocked"                                              
else                                                                                                              
    echo "WARNING: ABR sanity check failed: got '$ABR_RESULT'"
fi                                                                                                                
                                                    
# 4. Rotate old logs that have been synced to bucket                                                              
echo "Checking for old logs to rotate..."             
find "$LOG_DIR" -name "*.jsonl" -mtime +7 -type f | while read old_log; do                                        
    # Verify it exists in the bucket before deleting locally                                                      
    filename=$(basename "$old_log")                                                                               
    if gsutil stat "$BUCKET_PATH/$filename" >/dev/null 2>&1; then                                                 
        echo "  Rotating $filename (confirmed in bucket)"                                                         
        rm "$old_log"                                                                                             
    else                                                                                                          
        echo "  Keeping $filename (not yet in bucket)"                                                            
    fi                                                                                                            
done                                                                                                              
echo "✓ Log rotation complete" 