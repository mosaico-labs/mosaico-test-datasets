Here need to go the instructions to load the SugarBeets-Dataset.
Link: [link to the website](http://www.ipb.uni-bonn.de/datasets_IJRR2017/rosbags)

To download locally all the `.bags` in at `<path>` (by default path is: `${HOME}/rosbags/`)

``` bash
./download_ijrr_sugar_beet_2016_rosbag_data.sh <path>
```

To upload the datasets in Mosaico Server (activate VPN and locally mount Server folder):

``` bash
./download_ijrr_sugar_beet_2016_rosbag_data.sh /mnt/datasets/rosbags
```