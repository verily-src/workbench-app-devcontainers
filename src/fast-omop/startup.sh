#!/bin/bash                                                                                                       
                                                                                                                    
# Start cron for log syncing                                                                                      
service cron start

# Run FastOMOP post-startup checks                                                                                
bash /app/post-startup.sh
                                                                                                                
# Start the Agno orchestration service                                             
cd /app/agno_fastomop
python -m agno_fastomop.run_agent
