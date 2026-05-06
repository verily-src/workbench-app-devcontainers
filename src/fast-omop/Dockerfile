FROM python:3.13                                                                                                           
                       
  WORKDIR /app
  COPY requirements.txt .                                                                                                            
  RUN pip install -r requirements.txt
  COPY . . 
  RUN apt-get update && apt-get install -y cron \                                                                   
      && chmod +x /app/sync_logs.sh \ 
      && chmod +x /app/startup.sh \   
      && chmod +x /app/post-startup-fastomop.sh \               
      && echo "*/15 * * * * /app/sync_logs.sh >> /var/log/fastomop/sync.log 2>&1" | crontab -                                                                                                                          
  
  CMD ["bash", "/app/startup.sh"]