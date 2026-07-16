Here need to go the instructions to load the Autoware-Dataset.
Link: [link to the website](https://drive.google.com/drive/folders/1BMPcUhjq_BCLi521X88WpujoOiEi3_CJ)

To download locally all the `.bags` in at `<path>` (by default path is: `${HOME}/rosbags/`)

``` bash
./download_autoware.sh <path>
```

To upload the datasets in Mosaico Server (activate VPN and locally mount Server folder):

``` bash
./download_autoware.sh /mnt/datasets/rosbags
```