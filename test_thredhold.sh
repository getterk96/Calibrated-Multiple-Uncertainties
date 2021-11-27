device=4
threshold=0.6
source=$1
target=$2
src_threshold=$3

CUDA_VISIBLE_DEVICES=$device python3 src/main.py /data/office -d Office31 -s data/office/${source}.txt -t data/office/${target}.txt --n_share 10 --n_source_private 10 --n_total 31 --epochs 20 --threshold ${threshold} --source_threshold ${src_threshold} --seed 2021 -b 32
