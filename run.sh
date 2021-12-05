comment=$1
threshold=$2

nohup bash run_4.sh ${comment} ${threshold} &
nohup bash run_5.sh ${comment} ${threshold} &
nohup bash run_6.sh ${comment} ${threshold} &
nohup bash run_7.sh ${comment} ${threshold} &
