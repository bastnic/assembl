define(['backbone', 'zepto', 'app'], function(Backbone, $, app){
    'use strict';

    /**
     * @class SynthesisModel
     */
    var SynthesisModel = Backbone.Model.extend({

        /**
         * @init
         */
        initialize: function(){
            //this.on('change:read', this.onAttrChange, this);
        },

        /**
         * The url
         * @type {String}
         */
        urlRoot: app.getApiUrl('synthesis'),

        /**
         * Default values
         * @type {Object}
         */
        defaults: {
            title: 'Add a title'
        }

    });



    return {
        Model: SynthesisModel
    };

});