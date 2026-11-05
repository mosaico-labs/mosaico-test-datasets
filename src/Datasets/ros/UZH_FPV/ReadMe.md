Here need to go the instructions to load the UZH-FPV-Dataset.
Link: [link to the website](https://fpv.ifi.uzh.ch/datasets/)

To download locally all the `.bags` in at `<path>` (by default path is: `${HOME}/rosbags/`)

``` bash
./download_uzh_fpv.sh <path>
```

To upload the datasets in Mosaico Server (activate VPN and locally mount Server folder):

``` bash
./download_uzh_fpv.sh /mnt/datasets/rosbags
```