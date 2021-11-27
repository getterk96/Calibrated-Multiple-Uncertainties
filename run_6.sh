echo $$

device=6
threshold=0.6
src_threshold=0.85

CUDA_VISIBLE_DEVICES=$device python3 src/main.py /data/office -d Office31 -s data/office/dslr.txt -t data/office/amazon.txt --n_share 10 --n_source_private 10 --n_total 31 --epochs 20 --threshold ${threshold} --source_threshold ${src_threshold} --seed 2021 -b 16 -i 500 | tee logs/da_${threshold}_${src_threshold}.log

CUDA_VISIBLE_DEVICES=$device python3 src/main.py /data/office -d Office31 -s data/office/amazon.txt -t data/office/dslr.txt --n_share 10 --n_source_private 10 --n_total 31 --epochs 20 --threshold ${threshold} --source_threshold ${src_threshold} --seed 2021 -b 16 -i 500 | tee logs/ad_${threshold}_${src_threshold}.log
