echo $$

device=5
threshold=0.6
src_threshold=0.85
comment=$1

CUDA_VISIBLE_DEVICES=$device python3 src/main.py /data/office -d Office31 \
    -s data/office/webcam.txt \
    -t data/office/amazon.txt \
    --n_share 10 --n_source_private 10 --n_total 31 \
    --threshold ${threshold} \
    --source_threshold ${src_threshold} \
    --seed 2021 -b 16 -i 500 --epochs 20 | tee logs/wa_${threshold}_${src_threshold}_${comment}.log

CUDA_VISIBLE_DEVICES=$device python3 src/main.py /data/office -d Office31 \
    -s data/office/dslr.txt \
    -t data/office/webcam.txt \
    --n_share 10 --n_source_private 10 --n_total 31 \
    --threshold ${threshold} \
    --source_threshold ${src_threshold} \
    --seed 2021 -b 16 -i 500 --epochs 20 | tee logs/dw_${threshold}_${src_threshold}_${comment}.log